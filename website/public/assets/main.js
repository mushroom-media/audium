// The only script on the page: the copy button of the install commands.
for (const button of document.querySelectorAll("button[data-copy]")) {
  const label = button.textContent;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = button.dataset.done;
    } catch {
      return;
    }
    setTimeout(() => (button.textContent = label), 1600);
  });
}
