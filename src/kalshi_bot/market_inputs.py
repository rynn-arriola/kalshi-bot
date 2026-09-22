"""Verified-source input adapters for advisory exits; no trading authority.

No universal event-risk inference. Timing reviews and member precision must be
supplied explicitly. REST serves missing full definitions, fees and milestones;
healthy lifecycle updates supersede cached fields and invalidate pending reads.
"""
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import math
import time

from .adapters import PriceBand
from .exits import ExitTerms
from .observability import NO_LOG
from .values import InvalidData, decimal, identity, integer, utc


def timestamp(value):
    if type(value) is not str or len(value) > 64:
        raise InvalidData('metadata timestamp required')
    try:
        return utc(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except ValueError:
        raise InvalidData('invalid metadata timestamp') from None


def tick_bands(rows):
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        raise InvalidData('bounded price ranges required')
    result = []
    for row in rows:
        if type(row) is not dict or any(type(row.get(k)) is not str for k in ('start', 'end', 'step')):
            raise InvalidData('fixed-point price ranges required')
        band = PriceBand(row['start'], row['end'], row['step'])
        if any(v % Decimal('.0001') for v in (band.start, band.end, band.step)):
            raise InvalidData('unsupported quote precision')
        result.append(band)
    if result[0].start != 0 or result[-1].end != 1 or any(a.end != b.start for a,b in zip(result,result[1:])):
        raise InvalidData('price ranges must cover the ordered unit interval')
    return tuple(result)


def rules_digest(market):
    fields = ('ticker', 'event_ticker', 'market_type', 'rules_primary', 'rules_secondary',
              'can_close_early', 'early_close_condition', 'strike_type', 'floor_strike',
              'cap_strike', 'functional_strike', 'custom_strike', 'primary_participant_key')
    if any(type(market.get(k)) is not str for k in ('rules_primary', 'rules_secondary')):
        raise InvalidData('complete market rules required')
    # REST decodes JSON numbers as Decimal. Preserve exact numeric semantics
    # in the review digest without lossy floats or arbitrary object reprs.
    def exact(value):
        if isinstance(value,Decimal):
            return {'decimal':format(decimal(value),'f')}
        raise TypeError('unsupported rule value')
    encoded = json.dumps({k: market.get(k) for k in fields}, sort_keys=True, separators=(',', ':'),
                         allow_nan=False, default=exact)
    if len(encoded) > 65536:
        raise InvalidData('market rules exceed review budget')
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class Market:
    ticker: str
    event: str
    exchange: int
    bands: tuple
    opens: datetime
    closes: datetime
    active: bool
    early: bool
    rules_hash: str


def parse_market(doc, ticker):
    row = doc['market']
    if row['ticker'] != ticker or row['market_type'] != 'binary':
        raise InvalidData('unsupported market identity/type')
    if row.get('mve_collection_ticker') or row.get('mve_selected_legs'):
        raise InvalidData('multivariate exit inputs unsupported')
    if decimal(row['notional_value_dollars']) != 1:
        raise InvalidData('only unit-dollar contracts supported')
    status = row['status']
    if status not in {'initialized', 'inactive', 'active', 'closed', 'determined', 'disputed', 'amended', 'finalized'}:
        raise InvalidData('unknown market status')
    if type(row['can_close_early']) is not bool:
        raise InvalidData('early-close flag required')
    opens, closes = timestamp(row['open_time']), timestamp(row['close_time'])
    if opens >= closes:
        raise InvalidData('invalid trading interval')
    return Market(identity(ticker), identity(row['event_ticker']), integer(row['exchange_index'],0,2**31-1),
                  tick_bands(row['price_ranges']), opens, closes, status=='active', row['can_close_early'], rules_digest(row))


def fee_pair(kind, multiplier):
    if kind is None and multiplier is None:
        return None
    if type(kind) is not str or multiplier is None:
        raise InvalidData('incomplete fee configuration')
    value = decimal(multiplier)
    if not 0 <= value <= 100:
        raise InvalidData('fee multiplier outside supported range')
    return kind, value


@dataclass(frozen=True)
class EventFees:
    ticker: str
    series: str
    exchange: int
    override: tuple | None


def parse_event(doc, ticker):
    row = doc['event']
    if row['event_ticker'] != ticker:
        raise InvalidData('event identity conflict')
    return EventFees(identity(ticker), identity(row['series_ticker']), integer(row['exchange_index'],0,2**31-1),
                     fee_pair(row.get('fee_type_override'), row.get('fee_multiplier_override')))


def parse_series(doc, ticker):
    row = doc['series']
    if row['ticker'] != ticker:
        raise InvalidData('series identity conflict')
    pair = fee_pair(row['fee_type'], row['fee_multiplier'])
    if pair is None:
        raise InvalidData('series fee configuration missing')
    return pair


def fee_changes(rows, ticker, event=False):
    if type(rows) not in (tuple, list) or len(rows) > 128:
        raise InvalidData('fee-change scope exceeds budget')
    result, seen = [], set()
    for row in rows:
        key = identity(row['id'])
        if key in seen or row['event_ticker' if event else 'series_ticker'] != ticker:
            raise InvalidData('fee-change identity/scope conflict')
        seen.add(key)
        pair = fee_pair(row['fee_type_override' if event else 'fee_type'],
                        row['fee_multiplier_override' if event else 'fee_multiplier'])
        if not event and pair is None:
            raise InvalidData('series fee change missing configuration')
        result.append((timestamp(row['scheduled_ts']), pair))
    return tuple(result)


@dataclass(frozen=True)
class TimingReview:
    """Caller-reviewed rules-to-milestone binding, not a live trading approval."""
    ticker: str
    event: str
    milestone_id: str
    milestone_type: str
    rules_hash: str
    review_reference: str
    valid_until: datetime
    early_close_reviewed: bool = False

    def __post_init__(self):
        for field in ('ticker','event','milestone_id','milestone_type','review_reference'):
            identity(getattr(self,field))
        if (type(self.rules_hash) is not str or len(self.rules_hash)!=64
                or any(c not in '0123456789abcdef' for c in self.rules_hash)
                or type(self.early_close_reviewed) is not bool):
            raise InvalidData('invalid timing review')
        object.__setattr__(self,'valid_until',utc(self.valid_until))


@dataclass(frozen=True)
class FeeProfile:
    """Verified balance precision; FCM/additional account fees remain unsupported."""
    balance_quantum: Decimal
    review_reference: str
    valid_until: datetime

    def __post_init__(self):
        value = decimal(self.balance_quantum)
        if value not in (Decimal('.0001'), Decimal('.01')):
            raise InvalidData('unsupported member balance precision')
        object.__setattr__(self,'balance_quantum',value)
        object.__setattr__(self,'valid_until',utc(self.valid_until))
        identity(self.review_reference)


def taker_bound(pair, profile):
    kind, multiplier = pair
    if kind not in {'quadratic','quadratic_with_maker_fees','quadratic_with_combo_maker_fees'}:
        return None
    # Worst p(1-p)=.25. At most 100 fills/contract at .01 minimum quantity.
    # Per fill: <1 microdollar model rounding + <balance quantum alignment.
    # Ignore rebates; deliberately conservative for ANY fragmentation/side.
    with localcontext() as ctx:
        ctx.prec = 40
        return Decimal('.0175')*multiplier + 100*(Decimal('.000001')+profile.balance_quantum)


@dataclass(frozen=True)
class Evidence:
    value: object
    observed: datetime
    expires: datetime
    mono: float
    ttl: float
    revision: int
    sources: tuple[str,...]
    stream_fields: tuple[str,...] = ()


@dataclass(frozen=True)
class InputResult:
    terms: ExitTerms
    blockers: tuple[str,...]
    provenance: tuple[tuple[str,str,int],...]
    generation: int


class ExitInputService:
    def __init__(self, reads, tickers, *, now, ttl, clock=time.monotonic, diagnostics=NO_LOG,
                 timing_reviews=(), fee_profile=None, candidate_reviews=()):
        if type(ttl) not in (int,float) or not math.isfinite(ttl) or not 0<ttl<=60:
            raise InvalidData('explicit metadata freshness budget up to 60 seconds required')
        if not 1<=len(tickers)<=1024 or len(set(tickers))!=len(tickers):
            raise InvalidData('bounded unique market input scope required')
        self.tickers = frozenset(identity(t) for t in tickers)
        self.reads, self.now, self.clock, self.ttl, self.diagnostics = reads, now, clock, ttl, diagnostics
        self.reviews = {}
        if type(candidate_reviews) is not tuple or len(candidate_reviews) > 128:
            raise InvalidData('bounded candidate review registry required')
        self.candidate_reviews = {}
        for review in candidate_reviews:
            if not isinstance(review, TimingReview) or review.ticker in self.candidate_reviews:
                raise InvalidData('candidate review identity conflict')
            self.candidate_reviews[review.ticker] = review
        for review in timing_reviews:
            if not isinstance(review,TimingReview) or review.ticker not in self.tickers or review.ticker in self.reviews:
                raise InvalidData('timing review scope conflict')
            self.reviews[review.ticker] = review
            if review.ticker in self.candidate_reviews and self.candidate_reviews[review.ticker] != review:
                raise InvalidData('active/candidate review conflict')
        if fee_profile is not None and not isinstance(fee_profile,FeeProfile):
            raise InvalidData('explicit fee profile required')
        self.fee_profile = fee_profile
        self.event_markets = {}
        for review in self.reviews.values():
            self.event_markets.setdefault(review.event,set()).add(review.ticker)
        self.values, self.epochs, self.pending, self.results, self.overlays = {}, {}, {}, {}, {}
        self.pending_scopes, self.retiring = {}, set()
        self.epoch_serial = 0
        self.read_scope = object()
        self.generation, self.sid, self.seq = 0, None, None
        self.connected = self.closed = False
        self.publish = self.revoke = None
        self.slots = asyncio.Semaphore(2)
        self.refreshing = set()
        self.listener = None

    def listen(self, callback):
        if self.listener is not None or not callable(callback):
            raise InvalidData('one metadata scheduler listener required')
        self.listener = callback

    def rebind_scope(self, tickers):
        """Control-plane only, with all metadata workers/dependencies idle."""
        tickers = frozenset(identity(t) for t in tickers)
        if (self.closed or not 1 <= len(tickers) <= 1024 or self.pending
                or self.retiring or self.refreshing):
            raise InvalidData('metadata scope replacement requires idle bounded service')
        removed = self.tickers-tickers
        for ticker in removed:
            self._clear_terms(ticker)
            self.reviews.pop(ticker,None)
        added = tickers-self.tickers
        self.tickers = tickers
        for event in tuple(self.event_markets):
            self.event_markets[event].difference_update(removed)
            if not self.event_markets[event]: self.event_markets.pop(event)
        for ticker in added:
            review = self.candidate_reviews.get(ticker)
            if review is not None:
                self.reviews[ticker] = review
                self.event_markets.setdefault(review.event, set()).add(ticker)
        self._prune_dependencies()

    def _notify(self, kind, ticker=None):
        if self.listener is not None:
            self.listener(kind, ticker)

    def set_review(self, ticker, review):
        if self.closed or ticker not in self.tickers or (review is not None and
                (not isinstance(review, TimingReview) or review.ticker != ticker)):
            raise InvalidData('review update outside managed scope')
        if review is None:
            self.reviews.pop(ticker, None)
            self.candidate_reviews.pop(ticker, None)
        else:
            self.reviews[ticker] = review
            if ticker in self.candidate_reviews:
                self.candidate_reviews[ticker] = review
        for event in tuple(self.event_markets):
            self.event_markets[event].discard(ticker)
            if not self.event_markets[event]:
                self.event_markets.pop(event)
        baseline = self.values.get(('market', ticker))
        for event in ((baseline.value.event if baseline is not None else None),
                      (review.event if review is not None else None)):
            if event is not None:
                self.event_markets.setdefault(event, set()).add(ticker)
        self._clear_terms(ticker)
        self._prune_dependencies()
        self._notify('changed', ticker)

    def set_fee_profile(self, profile):
        if self.closed or (profile is not None and not isinstance(profile, FeeProfile)):
            raise InvalidData('explicit fee profile required')
        self.fee_profile = profile
        for ticker in self.tickers:
            self._clear_terms(ticker)
            self._notify('changed', ticker)

    def next_refresh_at(self, ticker):
        """Monotonic deadline, with UTC policy/source expiries still enforced."""
        mono, now = self.clock(), utc(self.now())
        result = self.results.get(ticker)
        if result is None or result.generation != self.generation:
            return mono
        deadlines = [mono + (result.terms.valid_until-now).total_seconds()]
        for name, key, revision in result.provenance:
            evidence = self.values.get((name, key))
            if evidence is None or evidence.revision != revision or not self._fresh(evidence):
                return mono
            deadlines.append(evidence.mono+evidence.ttl)
        market = self.values[('market', ticker)].value
        deadlines.extend(mono+(stamp-now).total_seconds() for stamp in (market.opens, market.closes) if stamp>now)
        return max(mono, min(deadlines))

    def bind(self, publish, revoke):
        if self.publish is not None:
            raise InvalidData('input publisher already bound')
        self.publish, self.revoke = publish, revoke

    def _clear_terms(self, ticker):
        self.results.pop(ticker,None)
        if self.revoke is not None:
            self.revoke(ticker)

    def begin(self, generation):
        integer(generation,1,2**31-1)
        if self.closed or generation<=self.generation:
            raise InvalidData('input stream generation must advance')
        self.disconnect()
        self.generation = generation

    def subscribed(self, generation, sid):
        if generation!=self.generation or self.closed:
            raise InvalidData('stale lifecycle subscription')
        sid = integer(sid,1,2**63-1)
        if self.connected:
            if sid != self.sid:
                raise InvalidData('lifecycle subscription identity changed')
            return
        self.sid = sid
        self.connected = True
        self._notify('connected')

    def disconnect(self):
        self.connected = False
        self._notify('disconnected')
        self.sid = self.seq = None
        for target in tuple(self.pending):
            self._retire_pending(target)
        for ticker in self.tickers:
            self._clear_terms(ticker)
        self.values.clear()
        self.overlays.clear()
        self.event_markets = {}
        for review in self.reviews.values():
            self.event_markets.setdefault(review.event,set()).add(review.ticker)
        for key in tuple(self.epochs):
            self._bump(key)
        self._prune_dependencies()

    def _bump(self, target):
        # Never reuse a revision after a dependency has been retired. An old
        # in-flight response must not match a newly created key (ABA).
        self.epoch_serial += 1
        self.epochs[target] = self.epoch_serial
        return self.epoch_serial

    def _retire_pending(self, target):
        task = self.pending.pop(target, None)
        self.pending_scopes.pop(target, None)
        if task is not None:
            self.retiring.add(task)
            task.add_done_callback(self.retiring.discard)
            task.cancel()

    def _prune_dependencies(self):
        # The current market/review graph is the only retained cache authority.
        # Canceled tasks may still finish, but _bump and _load's .get guard keep
        # their old revisions from publishing after a key is retired/recreated.
        keep = {('market', ticker) for ticker in self.tickers}
        keep.update(('milestone', review.milestone_id) for review in self.reviews.values())
        for event in self.event_markets:
            keep.add(('event', event))
            keep.add(('event_fees', event))
            evidence = self.values.get(('event', event))
            if evidence is not None:
                keep.add(('series', evidence.value.series))
                keep.add(('series_fees', evidence.value.series))
        for target in tuple(self.epochs):
            if target not in keep:
                self._retire_pending(target)
                self.epochs.pop(target)
                self.values.pop(target, None)
                self.overlays.pop(target, None)

    def _fresh(self, evidence):
        return (evidence is not None and evidence.observed<=utc(self.now())<evidence.expires
                and 0<=self.clock()-evidence.mono<evidence.ttl)

    def _key(self, name, key):
        target = name,key
        if target not in self.epochs:
            if len(self.epochs)>=len(self.tickers)*8+16:
                self._prune_dependencies()
                if len(self.epochs)>=len(self.tickers)*8+16:
                    raise InvalidData('metadata dependency capacity exceeded')
            self._bump(target)
        return target

    async def _get(self, name, key):
        target = self._key(name,key)
        value = self.values.get(target)
        if self._fresh(value):
            return value
        task = self.pending.get(target)
        if task is not None and (task.done() or
                self.pending_scopes.get(target) != (self.generation, self.epochs[target])):
            self._retire_pending(target)
            task = None
        if task is None:
            if len(self.pending)>=16:
                raise InvalidData('metadata in-flight capacity exceeded')
            task = asyncio.create_task(self._load(target,self.epochs[target],self.generation))
            self.pending[target] = task
            self.pending_scopes[target] = self.generation, self.epochs[target]
            def done(t):
                if self.pending.get(target) is t:
                    self.pending.pop(target,None)
                    self.pending_scopes.pop(target,None)
                if not t.cancelled():
                    error = t.exception()
                    if error is not None:
                        self.diagnostics.emit('metadata_dependency_failed', error=error)
            task.add_done_callback(done)
        # asyncio.wait leaves the shared task alive on caller cancellation without
        # Python 3.14 shield's automatic raw-exception logging on later failure.
        await asyncio.wait((task,))
        try:
            return task.result()
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            raise InvalidData('metadata dependency superseded') from None
        except (KeyError, TypeError) as exc:
            raise InvalidData('incomplete metadata response') from exc

    async def _load(self, target, revision, generation):
        name,key = target
        async with self.slots:
            if not self.connected or generation!=self.generation or revision!=self.epochs.get(target):
                raise InvalidData('metadata read revoked before dispatch')
            observed, mono = utc(self.now()), self.clock()
            if not math.isfinite(mono): raise InvalidData('invalid input clock')
            async with asyncio.timeout(30):
                if name=='event_fees':
                    page = await self.reads.collect(name,reason='metadata',event_ticker=key,
                        coalesce_scope=(self.read_scope,generation,revision),
                        max_pages=4,max_rows=128,byte_limit=262144)
                    current_event = self.values.get(('event',key))
                    if current_event is None or any(row.get('series_ticker')!=current_event.value.series for row in page.rows):
                        raise InvalidData('event fee-change series conflict')
                    value = fee_changes(page.rows,key,True)
                else:
                    parameter = {'market':'ticker','event':'event_ticker','series':'series_ticker',
                                 'series_fees':'series_ticker','milestone':'milestone_id'}[name]
                    doc = (await self.reads.read(name,reason='metadata',
                        coalesce_scope=(self.read_scope,generation,revision),**{parameter:key})).payload
                    if name=='market': value = parse_market(doc,key)
                    elif name=='event': value = parse_event(doc,key)
                    elif name=='series': value = parse_series(doc,key)
                    elif name=='series_fees': value = fee_changes(doc['series_fee_change_arr'],key)
                    else:
                        row = doc['milestone']
                        if row['id']!=key or type(row['primary_event_tickers']) is not list or len(row['primary_event_tickers'])>1024:
                            raise InvalidData('milestone identity/scope conflict')
                        value = (identity(row['type']), timestamp(row['start_date']),
                                 tuple(identity(t) for t in row['primary_event_tickers']))
            expires = observed+timedelta(seconds=self.ttl)
            if name in ('event_fees','series_fees'):
                future = [stamp for stamp,_ in value if stamp>observed]
                if future: expires = min(expires,min(future))
            overlay = self.overlays.get(target,{})
            stream_fields = tuple(sorted(overlay))
            if any(getattr(value,field)!=expected for field,expected in overlay.items()):
                raise InvalidData('REST conflicts with latest lifecycle fields')
            sources = (name,'lifecycle') if stream_fields else (name,)
            result = Evidence(value,observed,expires,mono,self.ttl,revision+1,sources,stream_fields)
            if (self.closed or not self.connected or generation!=self.generation
                    or revision!=self.epochs.get(target) or not self._fresh(result)):
                raise InvalidData('metadata response stale or superseded')
            previous = self.values.get(target)
            self._bump(target)
            result = replace(result, revision=self.epochs[target])
            self.values[target] = result
            if name=='market':
                # Bounded reverse dependency index; no universe scan per event.
                for event in tuple(self.event_markets):
                    if key in self.event_markets[event] and event!=value.event:
                        self.event_markets[event].discard(key)
                        if not self.event_markets[event]: self.event_markets.pop(event)
                self.event_markets.setdefault(value.event,set()).add(key)
                if previous is not None and previous.value.event != value.event:
                    self._prune_dependencies()
            elif name == 'event' and previous is not None and previous.value.series != value.series:
                self._prune_dependencies()
            return result

    async def refresh(self, ticker):
        if self.closed or not self.connected or ticker not in self.tickers or self.publish is None:
            raise InvalidData('input service scope/stream/publisher unavailable')
        if ticker in self.refreshing or len(self.refreshing)>=8:
            raise InvalidData('bounded input refresh already busy')
        self.refreshing.add(ticker)
        generation = self.generation
        try:
            market = await self._get('market',ticker)
            m = market.value
            event = await self._get('event',m.event)
            e = event.value
            if m.exchange!=e.exchange:
                raise InvalidData('market/event exchange conflict')
            series, event_changes, series_changes = await asyncio.gather(self._get('series',e.series),
                self._get('event_fees',m.event),self._get('series_fees',e.series))
            inputs = [('market',ticker,market),('event',m.event,event),('series',e.series,series),
                      ('event_fees',m.event,event_changes),('series_fees',e.series,series_changes)]
            blockers, risk_at, bound = [], None, None
            now = utc(self.now())
            for changes,pair in ((event_changes.value,e.override),(series_changes.value,series.value)):
                past = [(stamp,change) for stamp,change in changes if stamp<=now]
                if past:
                    latest = max(stamp for stamp,_ in past)
                    if any(change!=pair for stamp,change in past if stamp==latest):
                        raise InvalidData('effective fee change not reflected in current metadata')
            review = self.reviews.get(ticker)
            if review is None or now>=review.valid_until:
                blockers.append('timing_review_missing')
            elif review.event!=m.event or review.rules_hash!=m.rules_hash or (m.early and not review.early_close_reviewed):
                blockers.append('timing_review_conflict')
            else:
                milestone = await self._get('milestone',review.milestone_id)
                inputs.append(('milestone',review.milestone_id,milestone))
                kind,start,primary = milestone.value
                if kind!=review.milestone_type or m.event not in primary:
                    blockers.append('milestone_binding_conflict')
                else: risk_at = start
            profile = self.fee_profile
            if profile is None or now>=profile.valid_until:
                blockers.append('fee_profile_missing')
            else:
                bound = taker_bound(e.override if e.override is not None else series.value,profile)
                if bound is None: blockers.append('fee_model_unsupported')
            expires = min(item.expires for _,_,item in inputs)
            if review is not None and risk_at is not None: expires = min(expires,review.valid_until)
            if profile is not None and bound is not None: expires = min(expires,profile.valid_until)
            # Never let a lifecycle update or another read overtake publication.
            if (generation!=self.generation or not self.connected or self.closed
                    or self.reviews.get(ticker) is not review or self.fee_profile is not profile
                    or utc(self.now())>=expires
                    or any(self.values.get((name,key)) is not item or not self._fresh(item) for name,key,item in inputs)):
                raise InvalidData('input evidence changed before publication')
            terms = ExitTerms(ticker,m.bands,min(v.observed for _,_,v in inputs),expires,m.closes,
                              event_risk_at=risk_at,taker_fee_per_contract_bound=bound,
                              active=m.active and m.opens<=utc(self.now())<m.closes)
            result = InputResult(terms,tuple(blockers),tuple((n,k,v.revision) for n,k,v in inputs),generation)
            self.results[ticker] = result
            self.publish(terms)
            self.diagnostics.emit('exit_inputs_published',market=ticker,generation=generation,
                                  blockers=result.blockers,blocker_count=len(blockers))
            return result
        except BaseException as exc:
            self._clear_terms(ticker)
            if not isinstance(exc,asyncio.CancelledError):
                self.diagnostics.emit('exit_inputs_failed',market=ticker,error=exc,generation=generation)
            raise
        finally:
            self.refreshing.discard(ticker)

    def ingest(self, event, *, generation):
        if generation!=self.generation: return False
        try:
            if not self.connected or self.closed or event['sid']!=self.sid:
                raise InvalidData('lifecycle stream scope invalid')
            seq = integer(event['seq'],1,2**63-1)
            if self.seq is not None and seq!=self.seq+1:
                raise InvalidData('lifecycle sequence gap')
            self.seq = seq
            kind,msg = event['type'],event['msg']
            if kind=='market_lifecycle_v2':
                ticker = identity(msg['market_ticker'])
                if ticker not in self.tickers: return True
                self._clear_terms(ticker)
                target = self._key('market',ticker)
                previous = self.values.pop(target,None)
                self._retire_pending(target)
                self._bump(target)
                self._notify('changed', ticker)
                event_type = msg['event_type']
                if event_type=='price_level_structure_updated':
                    update = {'bands':tick_bands(msg['price_ranges'])}
                elif event_type=='close_date_updated':
                    close = datetime.fromtimestamp(integer(msg['close_ts'],0,253402300799),timezone.utc)
                    if previous is not None and close<=previous.value.opens:
                        raise InvalidData('invalid stream trading close')
                    update = {'closes':close}
                elif event_type in ('deactivated','determined','settled'):
                    update = {'active':False}
                elif event_type=='activated':
                    if type(msg.get('is_deactivated',False)) is not bool:
                        raise InvalidData('invalid activation state')
                    update = {'active':not msg.get('is_deactivated',False)}
                else:
                    return True  # Created/metadata/new event requires full missing rules.
                self.overlays.setdefault(target,{}).update(update)
                if previous is not None:
                    market = replace(previous.value,**update)
                    self.values[target] = replace(previous,value=market,revision=self.epochs[target],
                        sources=tuple(sorted(set(previous.sources+('lifecycle',)))),
                        stream_fields=tuple(sorted(self.overlays[target])))
            elif kind in ('event_fee_update','event_lifecycle'):
                ticker = identity(msg['event_ticker'])
                target = ('event',ticker)
                previous = self.values.get(target)
                # Unknown events cannot grow caches from the universe-wide stream.
                affected = self.event_markets.get(ticker,())
                if target not in self.epochs and not affected: return True
                self._key(*target)
                self._retire_pending(target)
                self._bump(target)
                self.values.pop(target,None)
                for market in affected:
                    self._clear_terms(market)
                    self._notify('changed', market)
                if kind=='event_fee_update':
                    pair = fee_pair(msg['fee_type_override'],msg['fee_multiplier_override'])
                    self.overlays[target] = {'override':pair}
                    if previous is not None:
                        self.values[target] = replace(previous,value=replace(previous.value,override=pair),
                            revision=self.epochs[target],sources=tuple(sorted(set(previous.sources+('lifecycle',)))),
                            stream_fields=('override',))
            else:
                raise InvalidData('unsupported lifecycle message')
            return True
        except Exception:
            self.disconnect()
            raise

    async def close(self):
        self.closed = True
        self.disconnect()
        await asyncio.gather(*tuple(self.retiring),return_exceptions=True)
