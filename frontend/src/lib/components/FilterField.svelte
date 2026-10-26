<script lang="ts">
  // Text filter above a list. Reports the trimmed text after a pause in typing; `query` is the
  // filter currently applied (from the URL), followed on back/forward without eating a typed space.
  import { untrack } from "svelte";
  import Icon from "./Icon.svelte";

  let {
    query,
    placeholder,
    onchange,
  }: { query: string; placeholder: string; onchange: (q: string) => void } = $props();

  let value = $state(untrack(() => query));
  let timer: ReturnType<typeof setTimeout> | undefined;

  $effect(() => {
    const q = query;
    if (q !== untrack(() => value).trim()) value = q;
  });

  function input(v: string) {
    value = v;
    clearTimeout(timer);
    timer = setTimeout(() => onchange(v.trim()), 220);
  }

  function clear() {
    clearTimeout(timer);
    value = "";
    onchange("");
  }
</script>

<label class="filter">
  <Icon name="search" size={18} />
  <span class="sr-only">{placeholder}</span>
  <input
    type="search"
    {placeholder}
    {value}
    oninput={(e) => input(e.currentTarget.value)}
    onkeydown={(e) => e.key === "Enter" && e.currentTarget.blur()}
    autocomplete="off"
    autocapitalize="off"
    autocorrect="off"
    spellcheck="false"
    enterkeyhint="search"
  />
  {#if value}
    <button type="button" class="clear" aria-label="Filter löschen" onclick={clear}><Icon name="close" size={16} /></button>
  {/if}
</label>

<style>
  .filter {
    display: flex;
    align-items: center;
    gap: 10px;
    width: min(520px, 100%);
    height: 40px;
    padding: 0 6px 0 14px;
    border-radius: 20px;
    background: var(--surface-1);
    color: var(--text-muted);
  }
  .filter:focus-within {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  input {
    flex: 1;
    border: 0;
    background: none;
    color: var(--text);
    font: inherit;
    outline: none;
    min-width: 0;
    padding: 0;
  }
  /* Our own clear button replaces the browser's. */
  input::-webkit-search-cancel-button {
    display: none;
  }
  .clear {
    flex: none;
    width: 30px;
    height: 30px;
    border: 0;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
  }
  .clear:hover {
    color: var(--text);
  }
</style>
