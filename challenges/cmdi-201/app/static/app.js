document.getElementById('toolForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const target = document.getElementById('target').value;
  const tool = document.getElementById('tool').value;
  const loader = document.getElementById('loader');
  const result = document.getElementById('result');
  const error = document.getElementById('error');
  const output = document.getElementById('output');
  const badge = document.getElementById('commandBadge');

  result.classList.add('hidden');
  error.classList.add('hidden');
  loader.classList.remove('hidden');

  try {
    const form = new FormData();
    form.append('target', target);
    form.append('tool', tool);
    const res = await fetch('/api/lookup', { method: 'POST', body: form });
    const data = await res.json();

    loader.classList.add('hidden');
    if (res.ok) {
      badge.textContent = `${data.tool}: ${data.target}`;
      badge.className = 'badge ok';
      output.textContent = data.output;
      result.classList.remove('hidden');
    } else {
      error.textContent = data.error || 'Ошибка';
      error.classList.remove('hidden');
    }
  } catch (err) {
    loader.classList.add('hidden');
    error.textContent = err.message;
    error.classList.remove('hidden');
  }
});
