<script lang="ts">
  // A list of names as chips, plus a text field with suggestions to add one more.
  import Icon from "./Icon.svelte";
  import { t } from "../i18n.svelte";

  let {
    values = $bindable(),
    suggestions,
    labelledby,
    placeholder,
    morePlaceholder,
    onquery,
  }: {
    values: string[];
    suggestions: string[];
    labelledby: string;
    placeholder: string;
    morePlaceholder: string;
    /** Called while typing, to fetch suggestions from the server. */
    onquery?: (q: string) => void;
  } = $props();

  const listId = `chips-${Math.random().toString(36).slice(2)}`;
  let input = $state("");
  const has = (name: string) => values.some((v) => v.toLowerCase() === name.toLowerCase());
  const offered = $derived(suggestions.filter((s) => !has(s)));

  function add() {
    const name = input.trim();
    input = "";
    if (!name || has(name)) return;
    // Typed in another case? Use the library's spelling.
    values.push(suggestions.find((s) => s.toLowerCase() === name.toLowerCase()) ?? name);
  }
</script>

<div class="chips">
  {#each values as v, i (v)}
    <span class="chip">{v}<button aria-label={t("{name} entfernen", { name: v })} onclick={() => values.splice(i, 1)}><Icon name="close" size={14} /></button></span>
  {/each}
  <input bind:value={input} list={listId} aria-labelledby={labelledby} placeholder={values.length ? morePlaceholder : placeholder}
    oninput={() => onquery?.(input.trim())} onchange={add} onkeydown={(e) => e.key === "Enter" && add()} />
  <datalist id={listId}>{#each offered as s (s)}<option value={s}></option>{/each}</datalist>
</div>

<style>
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    min-width: 0;
  }
  input {
    flex: 1;
    min-width: 140px;
    box-sizing: border-box;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 3px 4px 3px 10px;
    border-radius: 999px;
    background: var(--surface-2);
    font-size: 0.88rem;
  }
  .chip button {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
  }
  .chip button:hover {
    background: var(--surface-1);
    color: var(--text);
  }
</style>
