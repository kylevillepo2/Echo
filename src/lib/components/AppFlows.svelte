<script lang="ts">
	import { flowsState } from '#lib/state/flows.svelte';
	import { studio } from '#lib/state/studio.svelte';
	import { allMonthIds, flowNode, fmtMonth, monthInfoFor, monthlyActivityFor, reasonColour, reasonLabel, sortedReasons, topReason, volumeOf } from '#lib/data/flows';
	import { fmtCount } from '#lib/utils/format';
	import { reportedSwitchCount } from '#lib/utils/flow-counts';
	import InsightChart from './InsightChart.svelte';
	import AppLogo from './AppLogo.svelte';

	let { appId, appName }: { appId: string; appName: string } = $props();
	const app = $derived(flowNode(appId));
	const periodLabel = $derived(flowsState.periodLabel);
	const showSwitchCounts = $derived(flowsState.showSwitches);
	let expanded = $state<string[]>([]);
	let previousApp = '';
	$effect(() => { if (previousApp !== appId) { previousApp = appId; expanded = []; } });
	const activity = $derived(monthlyActivityFor(new Set([appId])));

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

	const losing = $derived(byPartner('out'));
	const winning = $derived(byPartner('in'));
	const totalSwitches = $derived([...losing, ...winning].reduce((sum, partner) => sum + partner.switches, 0));
	const totalReviews = $derived(app?.observed ? volumeOf(app.id, flowsState.periodMonths) : null);

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
	<section class="summary" aria-label="Company switching summary">
		<div title="Switch reports involving this company in the selected period, not unique users"><strong class="num">{fmtCount(totalSwitches)}</strong><span>Reported switches</span></div>
		<div class="review-total" title="Review volume in the switching dataset for the selected period"><strong class="num">{totalReviews === null ? '—' : fmtCount(totalReviews)}</strong><span>{totalReviews === null ? 'Own reviews unavailable' : 'Reviews analyzed'}</span></div>
	</section>
	<section class="block company-chart">
		<div class="block-head"><span class="label-dim">Switching over time</span></div>
		<InsightChart points={allMonthIds.map((month) => ({ month, value: activity[month] ?? 0, partial: !monthInfoFor(new Set([appId]), month).full, low: false }))} label="Monthly reported switches involving {appName}" unit="switches" selectedMonth={flowsState.rangeEnd ? undefined : flowsState.period} onSelectMonth={(month) => flowsState.setPeriod(month)} />
	</section>
	{#each [{ title: showSwitchCounts ? 'Reported switches to other apps' : 'Mentions going to other apps', list: losing, direction: 'out' }, { title: showSwitchCounts ? 'Reported switches from other apps' : 'Mentions coming from other apps', list: winning, direction: 'in' }] as group (group.direction)}
		<section class="block">
			<div class="block-head">
				<span class="label-dim">{group.title}</span>
				<span class="soft num">{periodLabel}</span>
			</div>
			{#if group.list.length}
				{@const max = (showSwitchCounts ? group.list[0].switches : group.list[0].count) || 1}
				<div class="partners">
					{#each expanded.includes(group.direction) ? group.list : group.list.slice(0, 5) as row (row.s + '|' + row.t)}
						{@const partner = group.direction === 'out' ? row.t : row.s}
						{@const count = showSwitchCounts ? row.switches : row.count}
						<button class="partner" onclick={() => selectEdge(row)}>
							<span class="name"><AppLogo appId={partner} name={flowNode(partner)?.name ?? partner} size={24} /><span>{flowNode(partner)?.name ?? partner}</span></span>
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
				{#if group.list.length > 5}<button class="more" onclick={() => (expanded = expanded.includes(group.direction) ? expanded.filter((direction) => direction !== group.direction) : [...expanded, group.direction])}>{expanded.includes(group.direction) ? 'View less' : 'View more'}</button>{/if}
			{:else}
				<p class="muted">No reported switches in this period.</p>
			{/if}
		</section>
	{/each}
{/if}

<style>
	.block {
		padding: 12px 14px;
		border-bottom: 1px solid var(--line);
	}
	.summary { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; padding: 18px 14px; border-bottom: 1px solid var(--line); }
	.summary > div { display: flex; flex-direction: column; gap: 5px; }
	.summary strong { color: var(--lime); font-size: 32px; line-height: 1; }
	.summary .review-total strong { color: white; font-size: 24px; }
	.summary span { color: white; font-size: 11px; font-weight: 600; }
	.more { margin-top: 10px; color: var(--text-2); font-size: 11px; text-decoration: underline; text-underline-offset: 3px; }
	.block-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 8px;
	}
	.soft { font-size: 8.5px; color: var(--dim); }
	.muted, .empty p { font-size: 11.5px; line-height: 1.5; color: var(--muted); }
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
	.name { grid-area: name; display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 12.5px; color: var(--text); }
	.value { grid-area: value; display: flex; align-items: baseline; gap: 5px; font-size: 9px; color: var(--muted); }
	.value strong { font-size: 15px; font-weight: 600; color: var(--text-2); }
	.value.is-switch strong { font-size: 20px; color: var(--lime); }
	.meter { grid-area: meter; }
	.meta { grid-area: meta; display: flex; flex-wrap: wrap; gap: 4px 9px; font-family: var(--mono); font-size: 8.5px; color: var(--dim); }
	.reason { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); }
	.reason i { width: 6px; height: 6px; border-radius: 50%; }
</style>
