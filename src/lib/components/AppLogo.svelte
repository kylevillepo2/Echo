<script lang="ts">
	import { asset } from '$app/paths';
	import logos from '#lib/data/app-logos.json';
	let { appId, name, size = 32 }: { appId: string; name: string; size?: number } = $props();
	const uid = $props.id();
	const file = $derived((logos as Record<string, string>)[appId]);
	let failed = $state(false);
	let previous = '';
	$effect(() => { if (previous !== appId) { previous = appId; failed = false; } });
</script>

<svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="{name} logo" class="app-logo">
	<defs><clipPath id="{uid}-clip"><rect width="64" height="64" rx="14" /></clipPath></defs>
	<rect width="64" height="64" rx="14" fill="var(--panel-3)" />
	{#if file && !failed}
		<image href={asset(file as Parameters<typeof asset>[0])} width="64" height="64" preserveAspectRatio="xMidYMid slice" clip-path="url(#{uid}-clip)" onerror={() => (failed = true)} />
	{:else}
		<path d="M17 17h12v12H17zm18 0h12v12H35zM17 35h12v12H17zm18 0h12v12H35z" fill="var(--muted)" />
	{/if}
</svg>

<style>.app-logo { display: block; flex: none; overflow: visible; pointer-events: none; }</style>
