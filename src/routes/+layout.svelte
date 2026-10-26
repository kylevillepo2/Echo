<script lang="ts">
	import '../app.css';
	import { injectAnalytics } from '@vercel/analytics/sveltekit';
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';

	injectAnalytics({ mode: import.meta.env.DEV ? 'development' : 'production' });

	let { children }: LayoutProps = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{@render children()}
