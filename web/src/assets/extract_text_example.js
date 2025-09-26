// Minimal example JavaScript to call POST /extract-text with a file input
// and display the extracted text in a <pre id="extractedText"></pre> element.

async function extractTextFromFile(file) {
  const fd = new FormData();
  fd.append('policy', file, file.name);
  const res = await fetch('/extract-text', { method: 'POST', body: fd });
  const j = await res.json();
  return j;
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('policyFileInput');
  const out = document.getElementById('extractedText');
  const status = document.getElementById('extractStatus');
  if (!input) return;
  input.addEventListener('change', async (e) => {
    const f = input.files && input.files[0];
    if (!f) return;
    status && (status.textContent = 'Extracting...');
    try {
      const resp = await extractTextFromFile(f);
      if (resp.error) {
        status && (status.textContent = 'Error: ' + (resp.error || resp.detail || 'unknown'));
        out && (out.textContent = JSON.stringify(resp, null, 2));
      } else {
        status && (status.textContent = 'Extraction complete');
        out && (out.textContent = resp.text || '');
      }
    } catch (err) {
      status && (status.textContent = 'Fetch failed');
      out && (out.textContent = String(err));
    }
  });
});

// To use this snippet, add to an HTML page:
// <input id="policyFileInput" type="file" />
// <div id="extractStatus"></div>
// <pre id="extractedText"></pre>
// and include this script: <script src="/assets/extract_text_example.js"></script>
