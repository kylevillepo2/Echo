<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { studio } from '#lib/state/studio.svelte';
	import AppLogo from './AppLogo.svelte';
	let query = $state('');
	let active = $state(0);
	let input = $state<HTMLInputElement>();
	const matches = $derived.by(() => {
		const q = query.toLowerCase().replace(/[^a-z0-9]/g, '');
		return studio.apps.filter((app) => !q || `${app.name}${app.id}`.toLowerCase().replace(/[^a-z0-9]/g, '').includes(q))
			.sort((a, b) => {
				const rank = (name: string) => { const value = name.toLowerCase().replace(/[^a-z0-9]/g, ''); return value === q ? 0 : value.startsWith(q) ? 1 : 2; };
				return q ? rank(a.name) - rank(b.name) || a.name.localeCompare(b.name) : b.reviewCount - a.reviewCount;
			}).slice(0, 8);
	});
	$effect(() => { query; active = 0; });
	onMount(() => input?.focus());
	function choose(index: number) { const app = matches[index]; if (app) studio.openCompany(app.id); }
	async function onKeydown(event: KeyboardEvent) {
		if (event.metaKey || event.ctrlKey) return;
		if (!['Escape', 'ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return;
		event.preventDefault(); event.stopPropagation();
		if (event.key === 'Escape') return studio.closePalette();
		if (event.key === 'Enter') return choose(active);
		active = Math.max(0, Math.min(matches.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1)));
		await tick(); document.getElementById(`app-search-${active}`)?.scrollIntoView({ block: 'nearest' });
	}
</script>

<div class="backdrop" role="presentation" onclick={(event) => { if (event.target === event.currentTarget) studio.closePalette(); }}>
	<div class="spotlight" role="dialog" aria-modal="true" aria-label="Find an app" onkeydown={onKeydown} tabindex="-1">
		<div class="input-row">
			<svg width="22" height="22" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.4" /><path d="m13 13 4 4" stroke="currentColor" stroke-width="1.4" /></svg>
			<input bind:this={input} bind:value={query} placeholder="Search apps…" aria-label="Search apps" role="combobox" aria-autocomplete="list" aria-expanded={matches.length > 0} aria-controls="app-search-results" aria-activedescendant={matches.length ? `app-search-${active}` : undefined} spellcheck="false" />
			<button class="close" onclick={() => studio.closePalette()} aria-label="Close app search">esc</button>
		</div>
		<div class="results" id="app-search-results" role="listbox" aria-label="Apps">
			{#each matches as app, index (app.id)}
				<button class="result" class:active={active === index} role="option" aria-selected={active === index} id="app-search-{index}" onclick={() => choose(index)} onpointerenter={() => (active = index)}>
					<AppLogo appId={app.id} name={app.name} size={34} />
					<span class="name">{app.name}<span class="category">{app.categoryName}</span></span>
					{#if active === index}<span class="enter" aria-hidden="true">↵</span>{/if}
				</button>
			{:else}<p class="empty">No apps found.</p>{/each}
		</div>
	</div>
</div>

<style>
	.backdrop { position: fixed; inset: 0; display: flex; align-items: flex-start; justify-content: center; padding: 16vh 16px 24px; background: #0009; backdrop-filter: blur(7px); z-index: 100; }
	.spotlight { width: min(560px, 100%); border: 1px solid var(--line-bright); background: #141418f5; border-radius: 16px; box-shadow: 0 30px 120px #000a; overflow: hidden; }
	.input-row { display: flex; align-items: center; gap: 13px; padding: 20px; color: var(--muted); border-bottom: 1px solid var(--line); }
	input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 21px; color: white; }
	.close { font: 10px var(--mono); padding: 4px 6px; border: 1px solid var(--line-strong); border-radius: 4px; }
	.results { max-height: 52vh; overflow-y: auto; padding: 7px; }
	.result { display: flex; align-items: center; gap: 12px; padding: 10px 12px; width: 100%; text-align: left; border-radius: 9px; }
	.result.active { background: var(--panel-3); }
	.name { font-size: 13px; color: white; }
	.category { display: block; color: var(--muted); font-size: 10px; margin-top: 3px; }
	.enter { margin-left: auto; color: var(--muted); }
	.empty { margin: 15px; color: var(--muted); font-size: 12px; }
</style>
