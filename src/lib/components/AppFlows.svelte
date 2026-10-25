<script lang="ts">
	import { flowsState } from '#lib/state/flows.svelte';
	import { studio } from '#lib/state/studio.svelte';
	import { flowNode, flows, fmtMonth, reasonColour, reasonLabel, sortedReasons, topReason } from '#lib/data/flows';
	import { fmtCount } from '#lib/utils/format';
	import { reportedSwitchCount } from '#lib/utils/flow-counts';

	let { appId, appName }: { appId: string; appName: string } = $props();
	const app = $derived(flowNode(appId));
	const periodLabel = $derived(flowsState.period === 'all' ? 'all months' : fmtMonth(flowsState.period));
	const showSwitchCounts = $derived(flowsState.showSwitches);

	interface Partner {
		s: string;
		t: string;
		value: number;
		count: number;
		switches: number;
		reasons: Map<string, number>;
	}

	function byPartner(direction: 'out' | 'in'): Partner[] {
		const partners = new Map<string, Partner>();
		for (const agg of flowsState.aggregates.values()) {
			if (direction === 'out' ? agg.s !== appId : agg.t !== appId) continue;
			const id = direction === 'out' ? agg.t : agg.s;
			let partner = partners.get(id);
			if (!partner) {
				partner = { s: agg.s, t: agg.t, value: 0, count: 0, switches: 0, reasons: new Map() };
				partners.set(id, partner);
			}
			partner.value += agg.value;
			partner.count += agg.count;
			partner.switches += reportedSwitchCount(agg.kinds);
			for (const [reason, count] of agg.reasons) {
				partner.reasons.set(reason, (partner.reasons.get(reason) ?? 0) + count);
			}
		}
		return [...partners.values()].sort((a, b) =>
			(showSwitchCounts ? b.switches - a.switches : 0) || b.count - a.count || b.value - a.value
		);
	}

	const seenIn = $derived((app?.seenIn ?? []).map((id) => flowNode(id)?.name ?? id));
	const health = $derived(app?.observed ? app.health : undefined);
	const HEALTH_COLOURS: Record<string, string> = {
		'Positive switching balance': 'var(--pos)', Mixed: 'var(--cyan)',
		'Negative switching balance': 'var(--amber)', 'Strongly negative': 'var(--neg)', 'Too few reports': 'var(--dim)'
	};
	const years = $derived(Object.entries(app?.healthByPeriod ?? {}).sort(([a], [b]) => a.localeCompare(b)));
	const signed = (x: number | null) => (x === null ? '—' : `${x > 0 ? '+' : ''}${x.toFixed(2)}`);

	const losing = $derived(byPartner('out'));
	const winning = $derived(byPartner('in'));

	function selectEdge(row: Partner) {
		flowsState.selectEdge(row.s, row.t);
		studio.inspectorOpen = true;
	}
</script>

{#if !app}
	<section class="block empty" role="status">
		<span class="label-dim">No flow data</span>
		<p>Switching data isn’t available for {appName} yet. Its overview and reviews are still available.</p>
	</section>
{:else}
	<p class="note">
		{showSwitchCounts ? 'Reported switches' : 'Review mentions'} · {periodLabel}. Counts come from review reports, not measured users.
		{#if studio.categoryFilter}
			Use the map’s edge filters and timeline to change this view.
		{:else}
			Open this app’s cluster to filter edge types and periods.
		{/if}
	</p>
	{#if !app.observed}
		<p class="note">
			We don’t have {appName}’s own reviews. These flows come from reviews of
			{seenIn.length ? seenIn.join(', ') : 'other apps'}; moves between outside apps are not covered.
		</p>
	{:else if health}
		<section class="block">
			<div class="block-head">
				<span class="label-dim">Switching health · all months</span>
				<span class="bucket" style:color={HEALTH_COLOURS[health.bucket ?? ''] ?? 'var(--muted)'}>{health.bucket}</span>
			</div>
			<div class="health-row num">
				<span><b>{signed(health.score)}</b> score</span>
				<span>{health.reportsIn ?? 0} in</span>
				<span>{health.reportsOut ?? 0} out</span>
				{#each years as [year, h] (year)}
					<span title={h.bucket ?? ''}>{year}: {signed(h.score)}</span>
				{/each}
				{#if app.rating?.avg}
					<span>★ {app.rating.avg.toFixed(2)}{#if app.rating.trend !== null} ({app.rating.trend > 0 ? '+' : ''}{app.rating.trend.toFixed(2)}){/if}</span>
				{/if}
			</div>
			<p class="fine">
				{flows.meta.healthDefinition || 'Balance of switches reported in reviews.'}
				Score = (in − out) / (in + out); customers only, forced moves excluded; fewer than 20 reports = too few.
			</p>
		</section>
	{/if}
	{#each [{ title: showSwitchCounts ? 'Reported switches to other apps' : 'Mentions going to other apps', list: losing, direction: 'out' }, { title: showSwitchCounts ? 'Reported switches from other apps' : 'Mentions coming from other apps', list: winning, direction: 'in' }] as group (group.direction)}
		<section class="block">
			<div class="block-head">
				<span class="label-dim">{group.title}</span>
				<span class="soft num">{periodLabel}</span>
			</div>
			{#if group.list.length}
				{@const max = (showSwitchCounts ? group.list[0].switches : group.list[0].count) || 1}
				<div class="partners">
					{#each group.list.slice(0, 8) as row (row.s + '|' + row.t)}
						{@const partner = group.direction === 'out' ? row.t : row.s}
						{@const count = showSwitchCounts ? row.switches : row.count}
						<button class="partner" onclick={() => selectEdge(row)}>
							<span class="name">{flowNode(partner)?.name ?? partner}</span>
							<span class="value" class:is-switch={showSwitchCounts}>
								<strong class="num">{fmtCount(count)}</strong>
								<span>{showSwitchCounts ? (count === 1 ? 'switch' : 'switches') : 'mentions'}</span>
							</span>
							<span class="meter" style:color={reasonColour(topReason(row.reasons))}><i style:width="{(count / max) * 100}%"></i></span>
							<span class="meta">
								{#if showSwitchCounts && row.count > row.switches}
									<span>+ {fmtCount(row.count - row.switches)} other mentions</span>
								{/if}
								{#each sortedReasons(row.reasons).slice(0, 2) as [id, count] (id)}
									<span class="reason"><i style:background={reasonColour(id)}></i>{reasonLabel(id)} {count}</span>
								{/each}
							</span>
						</button>
					{/each}
				</div>
			{:else}
				<p class="muted">None in {periodLabel} for the visible edge types.</p>
			{/if}
		</section>
	{/each}
{/if}

<style>
	.block {
		padding: 12px 14px;
		border-bottom: 1px solid var(--line);
	}
	.block-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 8px;
	}
	.soft { font-size: 8.5px; color: var(--dim); }
	.note, .muted, .empty p { font-size: 11.5px; line-height: 1.5; color: var(--muted); }
	.note { margin: 0; padding: 10px 14px; border-bottom: 1px solid var(--line); }
	.muted { margin: 0; }
	.empty p { margin: 8px 0 0; }
	.partners { display: flex; flex-direction: column; }
	.partner {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas: 'name value' 'meter meter' 'meta meta';
		gap: 3px 8px;
		padding: 7px 6px;
		margin: 0 -6px;
		text-align: left;
		border-radius: 2px;
		transition: background var(--fast);
	}
	.partner:hover { background: var(--panel-2); }
	.name { grid-area: name; font-size: 12.5px; color: var(--text); }
	.value { grid-area: value; display: flex; align-items: baseline; gap: 5px; font-size: 9px; color: var(--muted); }
	.value strong { font-size: 15px; font-weight: 600; color: var(--text-2); }
	.value.is-switch strong { font-size: 20px; color: var(--lime); }
	.meter { grid-area: meter; }
	.meta { grid-area: meta; display: flex; flex-wrap: wrap; gap: 4px 9px; font-family: var(--mono); font-size: 8.5px; color: var(--dim); }
	.reason { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); }
	.reason i { width: 6px; height: 6px; border-radius: 50%; }
	.bucket { font-family: var(--mono); font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
	.health-row { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--muted); }
	.health-row b { color: var(--text); font-weight: 600; font-size: 13px; }
	.fine { margin: 7px 0 0; font-size: 10px; line-height: 1.45; color: var(--dim); }
</style>
