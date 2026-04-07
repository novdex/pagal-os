/**
 * PAGAL OS — Frontend JavaScript
 * Handles API calls, form submissions, auto-refresh, and status polling.
 */

const API_BASE = '';

// Read CSRF token from meta tag (injected by server-side template).
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';

// ---- Utility Functions ----

/**
 * Make a fetch request to the API and return JSON.
 * Automatically includes the CSRF token header on mutating requests.
 * @param {string} url - API endpoint
 * @param {object} options - fetch options
 * @returns {Promise<object>} Parsed JSON response
 */
async function apiCall(url, options = {}) {
    try {
        const headers = { 'Content-Type': 'application/json', ...options.headers };
        // Attach CSRF token on state-changing methods
        const method = (options.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && CSRF_TOKEN) {
            headers['X-CSRF-Token'] = CSRF_TOKEN;
        }
        const response = await fetch(API_BASE + url, {
            ...options,
            headers,
        });
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API call failed:', error);
        return { ok: false, error: error.message };
    }
}

/**
 * Show a result message in a result box element.
 * @param {string} elementId - ID of the result box
 * @param {string} message - Message to display
 * @param {boolean} isError - Whether this is an error message
 */
function showResult(elementId, message, isError = false) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.style.display = 'block';
    el.textContent = message;
    el.className = 'result-box ' + (isError ? 'error' : 'success');
}

// ---- Quick Run (Dashboard) ----

const quickRunForm = document.getElementById('quick-run-form');
if (quickRunForm) {
    quickRunForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const agentName = document.getElementById('quick-agent').value.trim();
        const task = document.getElementById('quick-task').value.trim();

        if (!agentName || !task) return;

        showResult('quick-result', 'Running agent... please wait.');
        const submitBtn = quickRunForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span>Running...';

        const data = await apiCall(`/api/agents/${encodeURIComponent(agentName)}/run`, {
            method: 'POST',
            body: JSON.stringify({ task: task }),
        });

        submitBtn.disabled = false;
        submitBtn.textContent = 'Run';

        if (data.ok) {
            let msg = data.output || 'Agent completed.';
            if (data.tools_used && data.tools_used.length > 0) {
                msg += '\n\nTools used: ' + data.tools_used.join(', ');
            }
            if (data.duration_seconds) {
                msg += '\nDuration: ' + data.duration_seconds.toFixed(1) + 's';
            }
            showResult('quick-result', msg, false);
        } else {
            showResult('quick-result', 'Error: ' + (data.error || data.detail || 'Unknown error'), true);
        }
    });
}

// ---- Create Agent ----

const createForm = document.getElementById('create-agent-form');
if (createForm) {
    createForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const description = document.getElementById('agent-description').value.trim();
        const modelSelect = document.getElementById('agent-model');
        const model = modelSelect ? modelSelect.value : null;

        if (!description) return;

        showResult('create-result', 'Creating agent... this may take a moment.');
        const submitBtn = createForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span>Creating...';

        const body = { description: description };
        if (model) body.model = model;

        const data = await apiCall('/api/agents', {
            method: 'POST',
            body: JSON.stringify(body),
        });

        submitBtn.disabled = false;
        submitBtn.textContent = 'Create Agent';

        if (data.ok) {
            showResult('create-result',
                `Agent "${data.name}" created successfully!\n\nRun it from the dashboard or CLI:\npython pagal.py run ${data.name} "your task"`,
                false
            );
            document.getElementById('agent-description').value = '';
        } else {
            showResult('create-result', 'Error: ' + (data.error || data.detail || 'Failed to create agent'), true);
        }
    });
}

// ---- Settings ----

const settingsForm = document.getElementById('settings-form');
if (settingsForm) {
    settingsForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const apiKey = document.getElementById('api-key').value;
        const defaultModel = document.getElementById('default-model').value;
        const ollamaUrl = document.getElementById('ollama-url').value;

        const data = await apiCall('/api/settings', {
            method: 'POST',
            body: JSON.stringify({
                openrouter_api_key: apiKey || null,
                default_model: defaultModel || null,
                ollama_url: ollamaUrl || null,
            }),
        });

        if (data.ok) {
            showResult('settings-result', 'Settings saved successfully!', false);
        } else {
            showResult('settings-result', 'Error: ' + (data.error || data.detail || 'Failed to save'), true);
        }
    });
}

// ---- Agent Actions (Dashboard) ----

/**
 * Prompt user for a task and run an agent.
 * @param {string} agentName - Name of the agent
 */
async function runAgentPrompt(agentName) {
    const task = prompt(`Enter task for "${agentName}":`);
    if (!task) return;

    showResult('quick-result', `Running ${agentName}... please wait.`);

    const data = await apiCall(`/api/agents/${encodeURIComponent(agentName)}/run`, {
        method: 'POST',
        body: JSON.stringify({ task: task }),
    });

    if (data.ok) {
        let msg = data.output || 'Agent completed.';
        if (data.tools_used && data.tools_used.length > 0) {
            msg += '\n\nTools used: ' + data.tools_used.join(', ');
        }
        showResult('quick-result', msg, false);
    } else {
        showResult('quick-result', 'Error: ' + (data.error || data.detail || 'Unknown error'), true);
    }
}

/**
 * Stop a running agent.
 * @param {string} agentName - Name of the agent
 */
async function stopAgent(agentName) {
    const data = await apiCall(`/api/agents/${encodeURIComponent(agentName)}/stop`, {
        method: 'POST',
    });

    if (data.ok) {
        showResult('quick-result', `Agent "${agentName}" stopped.`, false);
        refreshAgentStatuses();
    } else {
        showResult('quick-result', data.message || 'Agent is not running.', true);
    }
}

/**
 * Delete an agent after confirmation.
 * @param {string} agentName - Name of the agent
 */
async function deleteAgent(agentName) {
    if (!confirm(`Are you sure you want to delete "${agentName}"?`)) return;

    const data = await apiCall(`/api/agents/${encodeURIComponent(agentName)}`, {
        method: 'DELETE',
    });

    if (data.ok) {
        // Remove the card from DOM
        const card = document.querySelector(`.agent-card[data-name="${agentName}"]`);
        if (card) card.remove();
        showResult('quick-result', `Agent "${agentName}" deleted.`, false);
    } else {
        showResult('quick-result', 'Error: ' + (data.detail || 'Failed to delete'), true);
    }
}

// ---- Status Polling ----

/**
 * Refresh all agent status indicators on the dashboard.
 */
async function refreshAgentStatuses() {
    const data = await apiCall('/api/agents');
    if (!data.ok) return;

    for (const agent of data.agents) {
        const card = document.querySelector(`.agent-card[data-name="${agent.name}"]`);
        if (!card) continue;

        const dot = card.querySelector('.status-dot');
        if (dot) {
            dot.className = 'status-dot ' + (agent.status === 'running' ? 'status-running' : 'status-idle');
        }

        const badge = card.querySelector('.badge-status');
        if (badge) {
            badge.textContent = agent.status;
        }
    }
}

// ---- Logs ----

/**
 * Fetch and display logs for an agent.
 * @param {string} agentName - Name of the agent
 */
async function fetchLogs(agentName) {
    const container = document.getElementById('log-container');
    if (!container) return;

    const data = await apiCall(`/api/agents/${encodeURIComponent(agentName)}/logs`);

    if (data.ok && data.logs && data.logs.length > 0) {
        container.innerHTML = data.logs
            .map(line => `<div class="log-entry">${escapeHtml(line)}</div>`)
            .join('');
        container.scrollTop = container.scrollHeight;
    } else {
        container.innerHTML = '<p class="log-placeholder">No logs available for this agent.</p>';
    }
}

/**
 * Escape HTML entities to prevent XSS.
 * @param {string} text - Raw text
 * @returns {string} Escaped HTML string
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---- PWA Service Worker Registration ----
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/sw.js')
            .then(reg => console.log('SW registered:', reg.scope))
            .catch(err => console.log('SW registration failed:', err));
    });
}
