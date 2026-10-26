<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { inject } from '@vercel/analytics';
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';

	onMount(() => {
		inject({ mode: import.meta.env.DEV ? 'development' : 'production' });
	});

	let { children }: LayoutProps = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{@render children()}
