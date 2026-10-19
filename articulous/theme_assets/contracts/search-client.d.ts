/** Optional shared search: immutable records, caller-owned matching and rendering. */
export interface SearchRecord {
  readonly url: string;
  readonly title: string;
  readonly description: string;
  readonly tags: readonly string[];
  readonly haystack: string;
}
export interface SearchRenderer<Entry, Container> {
  clear(): void;
  loading(): void;
  failed(error: unknown): void;
  create(): Container;
  append(container: Container, entry: Entry): void;
  publish(container: Container, count: number): void;
}
export interface SearchOptions<Entry extends SearchRecord, Container> {
  origin: string;
  load(signal: AbortSignal): Promise<unknown>;
  prepare(raw: unknown, url: URL): object;
  select(entries: readonly Entry[]): readonly Entry[];
  match(entries: readonly Entry[], query: string): readonly Entry[];
  renderer: SearchRenderer<Entry, Container>;
  batchSize?: number;
  schedule?(signal: AbortSignal): Promise<void>;
}
export interface SearchController {
  search(query: string): Promise<void>;
  reset(): void;
  dispose(): void;
}
export interface SearchIndexRow {
  readonly url: string;
  readonly title: string;
  readonly description: string;
  readonly tags?: readonly string[] | null;
  readonly [key: string]: unknown;
}
export interface SearchClientAPI {
  create<Entry extends SearchRecord, Container>(options: SearchOptions<Entry, Container>): SearchController;
  prepareIndex(data: unknown, origin: string, prepare: (row: SearchIndexRow, url: URL) => object): readonly SearchRecord[];
  normalizeSlug(name: string): string;
}
