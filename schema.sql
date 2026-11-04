-- VisualWatch v7. Run as project SQL editor owner before starting workers.
-- Safe to re-run. Stop older workers first; new queue operations require scopes.
begin;
select pg_advisory_xact_lock(hashtext('tigerwatch-v4-schema'));

create table if not exists public.tigerwatch_queue (
  id text primary key,
  source text not null,
  data jsonb not null default '{}'::jsonb check (jsonb_typeof(data)='object'),
  status text not null default 'pending' check (status in
    ('pending','processing','retry','alerted','rejected','unsupported','dead','review')),
  progress jsonb not null default '{}'::jsonb check (jsonb_typeof(progress)='object'),
  result jsonb not null default '{}'::jsonb check (jsonb_typeof(result)='object'),
  attempts integer not null default 0 check (attempts>=0),
  next_attempt double precision not null default 0,
  first_seen double precision not null,
  updated_at double precision not null,
  lease_token text,
  leased_until double precision not null default 0,
  last_error text not null default ''
);
create index if not exists tw_queue_due on public.tigerwatch_queue(status,next_attempt,first_seen);
create table if not exists public.tigerwatch_counters (
  day date not null,
  resource text not null check (resource in ('ai','alerts','digests')),
  used integer not null default 0 check (used>=0),
  last_at double precision not null default 0,
  primary key(day,resource)
);
-- Existing v6 tables keep their original CHECK after CREATE IF NOT EXISTS.
-- Replace that named constraint so a migrated store supports digest reservations.
alter table public.tigerwatch_counters drop constraint if exists tigerwatch_counters_resource_check;
alter table public.tigerwatch_counters add constraint tigerwatch_counters_resource_check
  check (resource in ('ai','alerts','digests'));
create table if not exists public.tigerwatch_kv (key text primary key, value jsonb not null);
create table if not exists public.tigerwatch_hashtag_windows (
  account text not null, tag text not null, started double precision not null,
  primary key(account,tag)
);
create table if not exists public.tigerwatch_source_claims (source text primary key, claimed_at double precision not null);
create table if not exists public.tigerwatch_feedback (
  id text primary key, verdict text not null check (verdict in ('correct','incorrect','uncertain')),
  updated_at double precision not null
);
create table if not exists public.tigerwatch_image_cache (
  scope text not null, key text not null, decision jsonb check (decision is null or jsonb_typeof(decision)='object'),
  expires_at double precision not null default 0, lease_token text,
  leased_until double precision not null default 0, updated_at double precision not null,
  primary key(scope,key)
);
create index if not exists tw_cache_expiry on public.tigerwatch_image_cache(expires_at);


-- One-time v3 import preserves processed IDs, pending metadata, and today's quota.
-- Legacy tables remain for rollback/inspection; remove them after verifying migration.
do $migration$
begin
  if not exists (select 1 from public.tigerwatch_kv where key='migration/v3') then
    if to_regclass('public.tigerwatch_seen') is not null then
      execute $sql$insert into public.tigerwatch_queue(id,source,status,first_seen,updated_at)
        select id,source,status,extract(epoch from checked_at),extract(epoch from checked_at)
        from public.tigerwatch_seen where status in ('alerted','rejected','unsupported')
        on conflict(id) do nothing$sql$;
    end if;
    if to_regclass('public.tigerwatch_pending') is not null then
      execute $sql$insert into public.tigerwatch_queue(id,source,data,first_seen,updated_at)
        select id,source,data,extract(epoch from first_seen),extract(epoch from now())
        from public.tigerwatch_pending where jsonb_typeof(data)='object'
        on conflict(id) do nothing$sql$;
    end if;
    if to_regclass('public.tigerwatch_daily_usage') is not null then
      execute $sql$insert into public.tigerwatch_counters(day,resource,used)
        select day,'ai',used from public.tigerwatch_daily_usage
        on conflict(day,resource) do update set used=greatest(public.tigerwatch_counters.used,excluded.used)$sql$;
    end if;
    insert into public.tigerwatch_kv values('migration/v3','true'::jsonb);
  end if;
end;
$migration$;

-- v5: old IDs belong to the original tiger target. New target scopes share
-- counters/hashtag windows but have separate queue decisions and notifications.
update public.tigerwatch_queue set id='legacy-tiger-v4:'||id where position(':' in id)=0;

alter table public.tigerwatch_queue enable row level security;
alter table public.tigerwatch_counters enable row level security;
alter table public.tigerwatch_kv enable row level security;
alter table public.tigerwatch_hashtag_windows enable row level security;
alter table public.tigerwatch_source_claims enable row level security;
alter table public.tigerwatch_feedback enable row level security;
alter table public.tigerwatch_image_cache enable row level security;
revoke all on public.tigerwatch_queue, public.tigerwatch_counters, public.tigerwatch_kv,
  public.tigerwatch_hashtag_windows, public.tigerwatch_source_claims, public.tigerwatch_feedback, public.tigerwatch_image_cache from public, anon, authenticated;
grant select,insert,update,delete on public.tigerwatch_queue, public.tigerwatch_counters,
  public.tigerwatch_kv, public.tigerwatch_hashtag_windows, public.tigerwatch_source_claims, public.tigerwatch_feedback, public.tigerwatch_image_cache to service_role;

-- Invoker security: no anonymous SECURITY DEFINER escalation. The server-only
-- service_role already bypasses RLS; clients get neither tables nor RPC access.
create or replace function public.tigerwatch_state(op text, payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security invoker set search_path = ''
as $function$
declare
  t double precision := extract(epoch from clock_timestamp());
  d date := (clock_timestamp() at time zone 'UTC')::date;
  q public.tigerwatch_queue%rowtype;
  c public.tigerwatch_counters%rowtype;
  ic public.tigerwatch_image_cache%rowtype;
  dg public.tigerwatch_counters%rowtype;
  health_key text;
  item jsonb;
  patch jsonb;
  answer jsonb;
  n integer;
  lim integer;
  gap double precision;
begin
  if jsonb_typeof(payload)<>'object' then raise exception 'invalid payload'; end if;
  if op='enqueue' then
    if jsonb_typeof(payload->'items')<>'array' or jsonb_array_length(payload->'items')>50 then
      raise exception 'invalid enqueue batch';
    end if;
    for item in select value from jsonb_array_elements(payload->'items') loop
      if (item->>'id') !~ '^(legacy-tiger-v4|[a-f0-9]{24}):[0-9]{1,50}$' or jsonb_typeof(item->'data')<>'object' then
        raise exception 'invalid queue item';
      end if;
      insert into public.tigerwatch_queue(id,source,data,first_seen,updated_at)
      values(item->>'id',item->>'source',item->'data',t,t)
      on conflict(id) do update set data=case
        when excluded.data->>'needs_hydration'='true'
          and public.tigerwatch_queue.data->>'needs_hydration' is distinct from 'true'
          and public.tigerwatch_queue.data?'permalink'
        then public.tigerwatch_queue.data else excluded.data end,updated_at=t
      where public.tigerwatch_queue.status in ('pending','retry') and public.tigerwatch_queue.leased_until<=t;
    end loop;
    return 'true'::jsonb;
  elsif op='claim' then
    select a.* into q from public.tigerwatch_queue a
    left join public.tigerwatch_source_claims s on s.source=a.source
    where (a.status in ('pending','retry') or (a.status='processing' and a.leased_until<=t))
      and a.next_attempt<=t and a.leased_until<=t
      and a.id like (payload->>'scope')||':%'
    order by coalesce(s.claimed_at,0),
      case when a.result->>'match'='true' or a.progress<>'{}'::jsonb then 0 else 1 end,
      a.first_seen desc,a.id
    for update of a skip locked limit 1;
    if not found then return 'null'::jsonb; end if;
    update public.tigerwatch_queue set status='processing',lease_token=payload->>'token',
      leased_until=t+least(900,greatest(120,(payload->>'lease')::integer)),updated_at=t
      where id=q.id returning * into q;
    insert into public.tigerwatch_source_claims values(q.source,t)
      on conflict(source) do update set claimed_at=t;
    return to_jsonb(q);
  elsif op='save' then
    patch := payload->'patch';
    if jsonb_typeof(patch)<>'object' or patch='{}'::jsonb or exists (
      select 1 from jsonb_object_keys(patch) k where k not in
        ('data','progress','result','status','attempts','last_error','next_attempt')) then
      raise exception 'invalid queue patch';
    end if;
    update public.tigerwatch_queue a set
      data=case when patch?'data' then patch->'data' else a.data end,
      progress=case when patch?'progress' then patch->'progress' else a.progress end,
      result=case when patch?'result' then patch->'result' else a.result end,
      status=coalesce(patch->>'status',a.status),
      attempts=coalesce((patch->>'attempts')::integer,a.attempts),
      last_error=coalesce(patch->>'last_error',a.last_error),
      next_attempt=coalesce((patch->>'next_attempt')::double precision,a.next_attempt),
      lease_token=case when (payload->>'release')::boolean then null else a.lease_token end,
      leased_until=case when (payload->>'release')::boolean then 0
        else t+least(900,greatest(120,(payload->>'lease')::integer)) end,
      updated_at=t
    where a.id=payload->>'id' and a.lease_token=payload->>'token'
      and a.leased_until>t and a.status='processing';
    get diagnostics n = row_count;
    return to_jsonb(n=1);
  elsif op='reserve' then
    if payload->>'resource' not in ('ai','alerts','digests') then raise exception 'invalid resource'; end if;
    lim := least(1000,greatest(0,(payload->>'limit')::integer));
    gap := least(60,greatest(0,(payload->>'interval')::double precision));
    insert into public.tigerwatch_counters(day,resource) values(d,payload->>'resource') on conflict do nothing;
    select * into c from public.tigerwatch_counters where day=d and resource=payload->>'resource' for update;
    if c.used>=lim then
      return jsonb_build_object('ok',false,'reason','daily','wait',86400-mod(t::numeric,86400)+1);
    end if;
    if t-c.last_at<gap then
      return jsonb_build_object('ok',false,'reason','pace','wait',gap-(t-c.last_at));
    end if;
    update public.tigerwatch_counters set used=used+1,last_at=t where day=d and resource=payload->>'resource';
    return jsonb_build_object('ok',true,'reason','reserved','wait',0);
  elsif op='reserve_digest' then
    lim := least(200,greatest(0,(payload->>'limit')::integer));
    gap := least(60,greatest(0,(payload->>'interval')::double precision));
    insert into public.tigerwatch_counters(day,resource) values(d,'digests') on conflict do nothing;
    select * into dg from public.tigerwatch_counters where day=d and resource='digests' for update;
    t := extract(epoch from clock_timestamp());
    if dg.used>=1 then
      return jsonb_build_object('ok',false,'reason','daily','wait',86400-mod(t::numeric,86400)+1,'resource','digests');
    end if;
    insert into public.tigerwatch_counters(day,resource) values(d,'alerts') on conflict do nothing;
    select * into c from public.tigerwatch_counters where day=d and resource='alerts' for update;
    t := extract(epoch from clock_timestamp());
    if c.used>=lim then
      return jsonb_build_object('ok',false,'reason','daily','wait',86400-mod(t::numeric,86400)+1,'resource','alerts');
    end if;
    if t-c.last_at<gap then
      return jsonb_build_object('ok',false,'reason','pace','wait',gap-(t-c.last_at),'resource','alerts');
    end if;
    update public.tigerwatch_counters set used=used+1,last_at=t where day=d and resource in ('alerts','digests');
    return jsonb_build_object('ok',true,'reason','reserved','wait',0,'resource','digests');
  elsif op in ('run_begin','run_finish') then
    if coalesce(payload->>'scope','') !~ '^(legacy-tiger-v4|[a-f0-9]{24})$'
      or coalesce(payload->>'token','') !~ '^[A-Za-z0-9_-]{1,128}$' then raise exception 'invalid run identity'; end if;
    health_key := 'health/'||(payload->>'scope')||'/last';
    perform pg_advisory_xact_lock(hashtext(health_key));
    t := extract(epoch from clock_timestamp());
    select value into answer from public.tigerwatch_kv where key=health_key;
    if op='run_begin' then
      if (payload->>'lease')::integer not between 120 and 1800 then raise exception 'invalid run lease'; end if;
      if answer->>'status'='running' and coalesce((answer->>'leased_until')::double precision,0)>t then return 'false'::jsonb; end if;
      answer := jsonb_build_object('id',payload->>'token','started_at',t,'leased_until',t+(payload->>'lease')::integer,'status','running');
    else
      if answer->>'id' is distinct from payload->>'token' or answer->>'status' is distinct from 'running'
        or coalesce((answer->>'leased_until')::double precision,0)<=t then return 'false'::jsonb; end if;
      if payload->>'status' not in ('completed','partial','failed','interrupted') then raise exception 'invalid run status'; end if;
      if payload->'metrics' is not null and payload->'metrics'<>'null'::jsonb then
        if jsonb_typeof(payload->'metrics')<>'object' or (select count(*) from jsonb_object_keys(payload->'metrics'))>64
          or exists(select 1 from jsonb_each(payload->'metrics') e where e.key !~ '^[a-z][a-z0-9_]{0,63}$'
            or jsonb_typeof(e.value)<>'number' or (e.value)::text::numeric<0) then raise exception 'invalid run metrics'; end if;
      end if;
      if payload->>'error' is not null and payload->>'error' !~ '^[A-Za-z0-9_:.-]{1,96}$' then raise exception 'invalid run error'; end if;
      answer := answer||jsonb_build_object('finished_at',t,'status',payload->>'status');
      if payload->'metrics' is not null and payload->'metrics'<>'null'::jsonb then answer := answer||jsonb_build_object('metrics',payload->'metrics'); end if;
      if payload->>'error' is not null then answer := answer||jsonb_build_object('error',payload->>'error'); end if;
    end if;
    insert into public.tigerwatch_kv values(health_key,answer) on conflict(key) do update set value=excluded.value;
    return 'true'::jsonb;
  elsif op='tag' then
    perform pg_advisory_xact_lock(hashtext('tigerwatch-tag/'||(payload->>'account')));
    delete from public.tigerwatch_hashtag_windows where account=payload->>'account' and started<=t-604800;
    if exists (select 1 from public.tigerwatch_hashtag_windows where account=payload->>'account' and tag=payload->>'tag') then
      return 'true'::jsonb;
    end if;
    select count(*) into n from public.tigerwatch_hashtag_windows where account=payload->>'account';
    if n>=30 then return 'false'::jsonb; end if;
    insert into public.tigerwatch_hashtag_windows values(payload->>'account',payload->>'tag',t);
    return 'true'::jsonb;
  elsif op='kv_get' then
    select value into answer from public.tigerwatch_kv where key=payload->>'key';
    return coalesce(answer,'null'::jsonb);
  elsif op='kv_set' then
    insert into public.tigerwatch_kv values(payload->>'key',payload->'value')
    on conflict(key) do update set value=excluded.value;
    return 'true'::jsonb;
  elsif op='maintain' then
    update public.tigerwatch_queue set
      status=case when result->>'sending'='true' then 'review' else 'dead' end,
      last_error=case when result->>'sending'='true' then 'telegram:delivery_unknown' else 'queue_expired' end,
      data='{}'::jsonb,progress='{}'::jsonb,lease_token=null,leased_until=0,updated_at=t
    where status in ('pending','retry','processing') and first_seen<t-(payload->>'hours')::integer*3600 and leased_until<=t;
    update public.tigerwatch_queue set data='{}'::jsonb,progress='{}'::jsonb
      where status='review' and first_seen<t-(payload->>'hours')::integer*3600;
    delete from public.tigerwatch_queue where status in ('alerted','rejected','unsupported','dead','review')
      and updated_at<t-(payload->>'days')::integer*86400;
    delete from public.tigerwatch_counters where day<d-90;
    delete from public.tigerwatch_feedback f where not exists (select 1 from public.tigerwatch_queue a where a.id=f.id);
    delete from public.tigerwatch_image_cache where expires_at<=t and leased_until<=t;
    return 'true'::jsonb;
  elsif op='stats' then
    return jsonb_build_object('queue',coalesce((select jsonb_object_agg(a.status,a.n) from
      (select status,count(*) n from public.tigerwatch_queue where id like (payload->>'scope')||':%' group by status) a),'{}'::jsonb),
      'today',coalesce((select jsonb_object_agg(resource,used) from public.tigerwatch_counters where day=d),'{}'::jsonb));
  elsif op='inspect' then
    select to_jsonb(a) into answer from public.tigerwatch_queue a where id=payload->>'id';
    return coalesce(answer,'null'::jsonb);
  elsif op='review_list' then
    return coalesce((select jsonb_agg(to_jsonb(a)) from (
      select r.*,f.verdict as feedback,f.updated_at as feedback_at from public.tigerwatch_queue r
      left join public.tigerwatch_feedback f on f.id=r.id
      where r.id like (payload->>'scope')||':%' and r.status in ('review','alerted')
      order by r.updated_at desc limit 200) a),'[]'::jsonb);
  elsif op='dashboard' then
    return jsonb_build_object(
      'queue',coalesce((select jsonb_object_agg(a.status,a.n) from
        (select status,count(*) n from public.tigerwatch_queue where id like (payload->>'scope')||':%' group by status) a),'{}'::jsonb),
      'today',coalesce((select jsonb_object_agg(resource,used) from public.tigerwatch_counters where day=d),'{}'::jsonb),
      'backlog',(select jsonb_build_object('pending',count(*),
        'due',count(*) filter(where next_attempt<=t and leased_until<=t),
        'oldest_first_seen',min(first_seen), 'oldest_age_seconds',greatest(0,t-coalesce(min(first_seen),t)))
        from public.tigerwatch_queue where id like (payload->>'scope')||':%' and status in ('pending','retry','processing')),
      'feedback',coalesce((select jsonb_object_agg(a.verdict,a.n) from
        (select verdict,count(*) n from public.tigerwatch_feedback where id like (payload->>'scope')||':%' group by verdict) a),'{}'::jsonb));
  elsif op='feedback' then
    if payload->>'verdict' not in ('correct','incorrect','uncertain')
      or payload->>'id' not like (payload->>'scope')||':%' then raise exception 'invalid feedback'; end if;
    perform 1 from public.tigerwatch_queue where id=payload->>'id'
      and status in ('alerted','rejected','unsupported','dead','review') for update;
    if not found then return 'false'::jsonb; end if;
    insert into public.tigerwatch_feedback values(payload->>'id',payload->>'verdict',t)
      on conflict(id) do update set verdict=excluded.verdict,updated_at=t;
    return 'true'::jsonb;
  elsif op like 'cache_%' then
    if coalesce(payload->>'key','') !~ '^[a-f0-9]{64}$'
      or coalesce(payload->>'scope','') !~ '^(legacy-tiger-v4|[a-f0-9]{24})$' then
      raise exception 'invalid image cache key';
    end if;
    if op in ('cache_claim','cache_commit','cache_release') and
      coalesce(payload->>'token','') !~ '^[A-Za-z0-9_-]{1,128}$' then raise exception 'invalid cache token'; end if;
    if op in ('cache_put','cache_commit') and (jsonb_typeof(payload->'decision') is distinct from 'object'
      or octet_length((payload->'decision')::text)>16384) then raise exception 'invalid cache decision'; end if;
    if op='cache_claim' and ((payload->>'lease')::integer not between 60 and 600) then
      raise exception 'invalid cache lease'; end if;
    -- Scope lock keeps both per-key claims and the bounded eviction atomic.
    perform pg_advisory_xact_lock(hashtext('visualwatch-cache/'||(payload->>'scope')));
    t := extract(epoch from clock_timestamp());
    select * into ic from public.tigerwatch_image_cache where scope=payload->>'scope' and key=payload->>'key';
    if op='cache_get' then
      return case when ic.decision is not null and ic.expires_at>t then ic.decision else 'null'::jsonb end;
    elsif op='cache_invalidate' then
      delete from public.tigerwatch_image_cache where scope=payload->>'scope' and key=payload->>'key' and leased_until<=t;
      get diagnostics n = row_count;
      return to_jsonb(n=1);
    elsif op='cache_release' then
      delete from public.tigerwatch_image_cache where scope=payload->>'scope' and key=payload->>'key' and lease_token=payload->>'token';
      get diagnostics n = row_count;
      return to_jsonb(n=1);
    elsif op='cache_commit' then
      update public.tigerwatch_image_cache set decision=payload->'decision',expires_at=t+604800,
        lease_token=null,leased_until=0,updated_at=t
        where scope=payload->>'scope' and key=payload->>'key' and lease_token=payload->>'token' and leased_until>t;
      get diagnostics n = row_count;
      return to_jsonb(n=1);
    elsif op='cache_claim' then
      if ic.decision is not null and ic.expires_at>t then return jsonb_build_object('status','hit','value',ic.decision); end if;
      if ic.leased_until>t then return jsonb_build_object('status','busy','wait',greatest(1,ic.leased_until-t)); end if;
    elsif op='cache_put' then
      if ic.leased_until>t then return 'false'::jsonb; end if;
    else raise exception 'unknown cache operation';
    end if;
    if ic.key is null and (select count(*) from public.tigerwatch_image_cache where scope=payload->>'scope')>=5000 then
      delete from public.tigerwatch_image_cache where (scope,key) in
        (select scope,key from public.tigerwatch_image_cache where scope=payload->>'scope' and leased_until<=t order by updated_at limit 1);
      if (select count(*) from public.tigerwatch_image_cache where scope=payload->>'scope')>=5000 then
        return case when op='cache_claim' then jsonb_build_object('status','busy','wait',60) else 'false'::jsonb end;
      end if;
    end if;
    if op='cache_claim' then
      insert into public.tigerwatch_image_cache(scope,key,lease_token,leased_until,updated_at)
        values(payload->>'scope',payload->>'key',payload->>'token',t+(payload->>'lease')::integer,t)
        on conflict(scope,key) do update set decision=null,expires_at=0,lease_token=excluded.lease_token,leased_until=excluded.leased_until,updated_at=t;
      return jsonb_build_object('status','claimed');
    else
      insert into public.tigerwatch_image_cache(scope,key,decision,expires_at,updated_at)
        values(payload->>'scope',payload->>'key',payload->'decision',t+604800,t)
        on conflict(scope,key) do update set decision=excluded.decision,expires_at=excluded.expires_at,lease_token=null,leased_until=0,updated_at=t;
      return 'true'::jsonb;
    end if;
  elsif op='retry' then
    select * into q from public.tigerwatch_queue where id=payload->>'id' and status in ('dead','review') for update;
    if not found then return 'false'::jsonb; end if;
    if q.last_error='telegram:delivery_unknown' and not coalesce((payload->>'acknowledge')::boolean,false) then
      raise exception 'delivery_unknown: acknowledge duplicate risk';
    end if;
    update public.tigerwatch_queue set status='retry',attempts=0,next_attempt=0,last_error='',first_seen=t,updated_at=t,
      result=jsonb_set(result,'{sending}','false'::jsonb)
      where id=q.id;
    return 'true'::jsonb;
  end if;
  raise exception 'unknown TigerWatch operation';
end;
$function$;
revoke all on function public.tigerwatch_state(text,jsonb) from public, anon, authenticated;
grant execute on function public.tigerwatch_state(text,jsonb) to service_role;
notify pgrst, 'reload schema';
commit;
