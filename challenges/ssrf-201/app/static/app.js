document.getElementById('fetchForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const url = document.getElementById('url').value;
  const loader = document.getElementById('loader');
  const result = document.getElementById('result');
  const error = document.getElementById('error');
  const output = document.getElementById('output');
  const badge = document.getElementById('statusBadge');

  result.classList.add('hidden');
  error.classList.add('hidden');
  loader.classList.remove('hidden');

  try {
    const form = new FormData();
    form.append('url', url);
    const res = await fetch('/api/fetch', { method: 'POST', body: form });
    const data = await res.json();

    loader.classList.add('hidden');
    if (res.ok) {
      badge.textContent = `HTTP ${data.status}`;
      badge.className = 'badge ok';
      output.textContent = JSON.stringify(data, null, 2);
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
