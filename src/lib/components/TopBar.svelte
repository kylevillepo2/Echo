<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
	import { asset } from '$app/paths';
</script>

<header class="topbar" aria-label="App navigation">
	<button class="brand" onclick={() => { studio.clearSelection(); studio.clearCategoryFilter(); }} aria-label="Return to app landscape">
		<img class="mark" src="{asset('echo.svg')}?v=raised" width="32" height="32" alt="" />
		<span class="wordmark">echo</span>
	</button>
	<button class="search" onclick={() => studio.openPalette()} aria-label="Search apps">
		<svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.4" /><path d="m13 13 4 4" stroke="currentColor" stroke-width="1.4" /></svg>
		<span>Find an app</span><kbd>⌘K</kbd>
	</button>
</header>

<style>
	.topbar { height: var(--header-h); flex: none; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; border-bottom: 1px solid var(--line); background: var(--bg); position: relative; z-index: 30; }
	.brand { display: flex; align-items: center; gap: 9px; }
	.mark { display: block; width: 32px; height: 32px; border-radius: 8px; background: var(--lime); }
	.wordmark { color: white; font: 700 23px var(--sans); letter-spacing: -0.05em; }
	.search { display: flex; align-items: center; gap: 10px; color: var(--muted); padding: 8px 11px; border: 1px solid var(--line); border-radius: 9px; min-width: 200px; text-align: left; font-size: 12px; }
	.search:hover { border-color: var(--line-bright); color: var(--text); }
	kbd { margin-left: auto; font: 10px var(--mono); color: var(--dim); }
	@media(max-width:600px) { .topbar { padding: 0 14px; } .search { min-width: 0; } .search kbd { display: none; } }
</style>
