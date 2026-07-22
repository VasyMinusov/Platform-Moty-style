function showError(msg) {
  const el = document.getElementById('error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

async function loadNotes() {
  try {
    const res = await fetch('/api/notes');
    if (!res.ok) throw new Error('Failed to load notes');
    const data = await res.json();
    const list = document.getElementById('notesList');
    if (!data.notes.length) {
      list.innerHTML = '<p class="muted">Заметок пока нет.</p>';
      return;
    }
    list.innerHTML = data.notes.map((n, i) => `
      <div class="note">
        <div class="note-meta">#${i + 1} · ${new Date().toLocaleDateString('ru-RU')}</div>
        <div>${escapeHtml(n)}</div>
      </div>
    `).join('');
  } catch (err) {
    showError(err.message);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

document.getElementById('noteForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = document.getElementById('noteText').value;
  try {
    const res = await fetch('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    if (!res.ok) throw new Error('Failed to save note');
    document.getElementById('noteText').value = '';
    await loadNotes();
  } catch (err) {
    showError(err.message);
  }
});

document.getElementById('adminBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/flag');
    const data = await res.json();
    const box = document.getElementById('flagBox');
    const out = document.getElementById('flagOutput');
    box.classList.remove('hidden');
    out.textContent = res.ok ? data.flag : (data.error || 'error');
  } catch (err) {
    showError(err.message);
  }
});

loadNotes();
