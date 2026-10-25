interface HotStateContext {
	data: Record<string, unknown>;
	accept(callback: () => void): void;
}

/** Vite can load the same store through different ?t= URLs after partial updates.
 *  Its hot data is shared by the canonical module path, so those imports must
 *  reuse one instance. Callers omit the context on the server/in production. */
export function hotSingleton<T>(
	hot: HotStateContext | undefined,
	key: string,
	create: () => T,
	onUpdate: () => void
): T {
	if (!hot) return create();
	if (!Object.prototype.hasOwnProperty.call(hot.data, key)) hot.data[key] = create();
	// Reload when a store's implementation changes rather than keeping old class methods.
	hot.accept(onUpdate);
	return hot.data[key] as T;
}
