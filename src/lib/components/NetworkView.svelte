<script lang="ts">
	import GraphCanvas from './GraphCanvas.svelte';
	import FlowWorkspace from './FlowWorkspace.svelte';
</script>

<section class="network" aria-label="App landscape">
	<FlowWorkspace><GraphCanvas /></FlowWorkspace>
</section>

<style>
	.network { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
</style>
