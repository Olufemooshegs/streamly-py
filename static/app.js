// --- 1. STATE-REACTIVE ANIMATED BACKGROUND ---
const canvas = document.getElementById('bg-canvas');
const ctx = canvas.getContext('2d');
let particles = [];
let currentState = 'idle';

function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}
window.addEventListener('resize', resize);
resize();

class Particle {
    constructor() {
        this.x = Math.random() * canvas.width;
        this.y = Math.random() * canvas.height;
        this.vx = (Math.random() - 0.5) * 0.5;
        this.vy = (Math.random() - 0.5) * 0.5;
        this.radius = Math.random() * 2 + 1;
    }
    update() {
        let speed = currentState === 'running' ? 2 : 0.5;
        if (currentState === 'disconnected') speed = 0.1;
        this.x += this.vx * speed;
        this.y += this.vy * speed;
        if (this.x < 0 || this.x > canvas.width) this.vx *= -1;
        if (this.y < 0 || this.y > canvas.height) this.vy *= -1;
    }
    draw() {
        if (currentState === 'running') {
            ctx.fillStyle = 'rgba(96, 165, 250, 0.8)';
            ctx.shadowBlur = 10;
            ctx.shadowColor = '#3b82f6';
        } else if (currentState === 'disconnected') {
            ctx.fillStyle = 'rgba(248, 113, 113, 0.4)';
            ctx.shadowBlur = 0;
        } else {
            ctx.fillStyle = 'rgba(167, 139, 250, 0.5)';
            ctx.shadowBlur = 0;
        }
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
    }
}
for (let i = 0; i < 80; i++) particles.push(new Particle());

function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let lineColor = 'rgba(148, 163, 184, 0.05)';
    if (currentState === 'running') lineColor = 'rgba(96, 165, 250, 0.15)';
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1;
    particles.forEach((p1, i) => {
        p1.update(); p1.draw();
        particles.slice(i + 1).forEach(p2 => {
            const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
            if (dist < 150) {
                ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
            }
        });
    });
    requestAnimationFrame(animate);
}
animate();

// --- 2. STATE & UI REFERENCES ---
const state = {
    runId: localStorage.getItem('runId') || null,
    idempotencyKey: localStorage.getItem('idemKey') || null,
    cursor: parseInt(localStorage.getItem('cursor') || '0', 10),
    seenEventIds: new Set(),
    duplicates: 0,
    eventSource: null,
    retryCount: 0,
    isCustomReconnect: false
};

const ui = {
    topic: document.getElementById('topic-input'),
    startBtn: document.getElementById('start-btn'),
    disconnectBtn: document.getElementById('disconnect-btn'),
    reconnectBtn: document.getElementById('reconnect-btn'),
    cancelBtn: document.getElementById('cancel-btn'),
    retryPostBtn: document.getElementById('retry-post-btn'),
    duplicateBtn: document.getElementById('duplicate-btn'),
    replayZeroBtn: document.getElementById('replay-zero-btn'),
    banner: document.getElementById('status-banner'),
    transcript: document.getElementById('transcript'),
    timeline: document.getElementById('timeline'),
    eventCount: document.getElementById('event-count'),
    showHeartbeats: document.getElementById('show-heartbeats'),
    runIdEl: document.getElementById('tel-run-id'),
    connEl: document.getElementById('tel-conn'),
    stateEl: document.getElementById('tel-state'),
    cursorEl: document.getElementById('tel-cursor'),
    latestEl: document.getElementById('tel-latest'),
    dupsEl: document.getElementById('tel-dups'),
    idemEl: document.getElementById('tel-idem'),
    lastFrameEl: document.getElementById('tel-last-frame'),
    stagePlan: document.getElementById('stage-plan'),
    stageInvestigate: document.getElementById('stage-investigate'),
    stageSummarize: document.getElementById('stage-summarize'),
    stageReview: document.getElementById('stage-review')
};

// --- 3. HELPERS ---
function updateTelemetry() {
    ui.runIdEl.innerText = state.runId ? state.runId.substring(0, 8) + '...' : '—';
    ui.idemEl.innerText = state.idempotencyKey || '—';
    ui.cursorEl.innerText = state.cursor;
    ui.dupsEl.innerText = state.duplicates;
    if (state.runId) ui.lastFrameEl.innerText = 'Just now';
}

function setConnectionStatus(status) {
    ui.connEl.innerText = status;
    ui.connEl.className = `value badge ${status === 'CONNECTED' || status === 'OPEN' ? 'green' : status === 'DISCONNECTED' ? 'red' : 'connecting'}`;
    if (status === 'DISCONNECTED') {
        currentState = 'disconnected';
        document.body.classList.add('disconnected');
    } else if (status === 'OPEN') {
        currentState = 'running';
        document.body.classList.remove('disconnected');
    }
}

function setRunState(status) {
    ui.stateEl.innerText = status;
    ui.stateEl.className = `value badge ${status === 'COMPLETED' ? 'green' : status === 'RUNNING' ? 'connecting' : status === 'FAILED' ? 'red' : 'outline'}`;
}

function showBanner(msg, type = 'success') {
    ui.banner.innerText = msg;
    ui.banner.style.display = 'block';
    ui.banner.className = `banner ${type}`;
    if (type === 'outline') {
        ui.banner.style.background = 'rgba(255, 255, 255, 0.05)';
        ui.banner.style.color = 'var(--text-main)';
        ui.banner.style.borderColor = 'var(--border)';
    } else if (type === 'danger') {
        ui.banner.style.background = 'var(--danger-bg)';
        ui.banner.style.color = 'var(--danger)';
        ui.banner.style.borderColor = 'var(--danger-border)';
    } else {
        ui.banner.style.background = 'var(--green-bg)';
        ui.banner.style.color = 'var(--green-text)';
        ui.banner.style.borderColor = 'var(--green-border)';
    }
}

function resetUI() {
    ui.transcript.innerHTML = '';
    ui.timeline.innerHTML = '';
    ui.eventCount.innerText = '0 events applied';
    state.seenEventIds.clear();
    state.duplicates = 0;
    state.cursor = 0;
    updateTelemetry();
    [ui.stagePlan, ui.stageInvestigate, ui.stageSummarize, ui.stageReview].forEach(el => {
        el.className = 'stage-card';
        el.querySelector('small').innerText = 'waiting';
    });
}

// --- 4. EVENT PROCESSING ---
function processEvent(event, isReplay = false) {
    if (state.seenEventIds.has(event.event_id)) {
        state.duplicates++;
        updateTelemetry();
        return; 
    }
    state.seenEventIds.add(event.event_id);

    state.cursor = Math.max(state.cursor, event.sequence);
    localStorage.setItem('cursor', state.cursor);
    updateTelemetry();
    ui.latestEl.innerText = event.sequence;

    if (event.type === 'heartbeat') {
        if (ui.showHeartbeats.checked) addTimelineItem(event, isReplay);
        return;
    }

    addTimelineItem(event, isReplay);

    if (event.type === 'token') {
        ui.transcript.innerHTML += `<span>${event.data.text}</span>`;
        ui.transcript.scrollTop = ui.transcript.scrollHeight;
    } else if (event.type === 'stage.started') {
        ui.transcript.innerHTML += `\n\n<strong style="color: #60a5fa">— ${event.data.stage.toUpperCase()} —</strong>\n`;
        const stageEl = document.getElementById(`stage-${event.data.stage}`);
        if (stageEl) {
            stageEl.className = 'stage-card active';
            stageEl.querySelector('small').innerText = 'processing';
        }
    } else if (event.type === 'checkpoint') {
        const stageEl = document.getElementById(`stage-${event.data.stage}`);
        if (stageEl) {
            stageEl.className = 'stage-card completed';
            stageEl.querySelector('small').innerText = 'checkpointed';
        }
        ui.transcript.innerHTML += `<div style="color:#4ade80; font-size:11px; margin-top:4px;">[checkpoint] ${event.data.stage} committed</div>\n`;
    
    // --- CHALLENGE 4: IDEMPOTENT SIDE EFFECT UI ---
    } else if (event.type === 'note.added') {
        ui.transcript.innerHTML += `\n<div style="color:#fbbf24; font-size:12px; margin-top:8px; background:rgba(245,158,11,0.1); padding:8px; border-radius:6px; border:1px solid rgba(245,158,11,0.3)">📝 <strong>Side Effect:</strong> ${event.data.content} (Committed to DB)</div>\n`;
        ui.transcript.scrollTop = ui.transcript.scrollHeight;
    } else if (event.type === 'note.skipped') {
        ui.transcript.innerHTML += `\n<div style="color:#f87171; font-size:12px; margin-top:8px; background:rgba(239,68,68,0.1); padding:8px; border-radius:6px; border:1px solid rgba(239,68,68,0.3)">🛑 <strong>Side Effect Blocked:</strong> ${event.data.reason}</div>\n`;
        ui.transcript.scrollTop = ui.transcript.scrollHeight;
    // ---------------------------------------------

    } else if (event.type === 'run.completed') {
        setRunState('COMPLETED');
        showBanner('Research run completed.', 'success');
        showControls(false);
        currentState = 'idle';
        ui.transcript.innerHTML += `\n\n<div style="color:#4ade80">[run.completed] ${event.data.message}</div>`;
    } else if (event.type === 'run.cancelled') {
        setRunState('CANCELLED');
        showBanner('Run cancelled by user.', 'danger');
        showControls(false);
        currentState = 'idle';
        ui.transcript.innerHTML += `\n\n<div style="color:#ef4444">[run.cancelled] ${event.data.reason}</div>`;
    }
}

function addTimelineItem(event, isReplay) {
    const item = document.createElement('div');
    item.className = 'timeline-item';
    let preview = event.data.text || event.data.stage || event.data.message || event.data.content || event.data.reason || '';
    item.innerHTML = `
        <span class="seq">#${event.sequence}</span>
        <span class="type">${event.type}</span>
        <span class="preview">${preview}</span>
        ${isReplay ? '<span class="badge-replay">REPLAY</span>' : ''}
    `;
    ui.timeline.appendChild(item);
    ui.timeline.scrollTop = ui.timeline.scrollHeight;
    const count = ui.timeline.querySelectorAll('.timeline-item').length;
    ui.eventCount.innerText = `${count} events applied`;
}

// --- 5. CONTROLS & NETWORK LOGIC ---
function showControls(isRunning) {
    ui.disconnectBtn.disabled = !isRunning;
    ui.reconnectBtn.disabled = isRunning;
    ui.cancelBtn.disabled = !isRunning;
    ui.retryPostBtn.disabled = !state.idempotencyKey;
    ui.duplicateBtn.disabled = !state.runId;
    ui.replayZeroBtn.disabled = !state.runId;
}

async function startRun(isRetry = false) {
    if (!isRetry) resetUI();
    if (!state.idempotencyKey) {
        state.idempotencyKey = crypto.randomUUID();
        localStorage.setItem('idemKey', state.idempotencyKey);
    }
    
    setConnectionStatus('CONNECTING');
    setRunState('RUNNING');
    showBanner('Connecting to stream...', 'outline');
    showControls(true);
    currentState = 'running';

    try {
        const res = await fetch('/api/runs', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Idempotency-Key': state.idempotencyKey
            },
            body: JSON.stringify({ topic: ui.topic.value })
        });
        const data = await res.json();
        state.runId = data.runId;
        localStorage.setItem('runId', state.runId);
        updateTelemetry();
        connectSSE();
    } catch (err) {
        showBanner('Failed to start run.', 'danger');
        currentState = 'disconnected';
    }
}

async function connectSSE() {
    if (state.eventSource) state.eventSource.close();
    
    // CHALLENGE 6: Check if the run still exists before connecting
    try {
        const check = await fetch(`/api/runs/${state.runId}/status`);
        if (check.status === 410 || check.status === 404) {
            showBanner('This run has expired and was pruned from the database. Starting fresh.', 'danger');
            
            // Clear local state
            localStorage.removeItem('runId');
            localStorage.removeItem('idemKey');
            localStorage.setItem('cursor', 0);
            state.runId = null;
            state.idempotencyKey = null;
            state.cursor = 0;
            
            resetUI();
            setConnectionStatus('IDLE');
            setRunState('IDLE');
            showControls(false);
            return; // Stop connecting
        }
    } catch (e) {
        console.error("Status check failed", e);
    }

    // Proceed with SSE connection if it exists
    const url = `/api/runs/${state.runId}/events?after=${state.cursor}`;
    state.eventSource = new EventSource(url);
    
    state.eventSource.onopen = () => {
        setConnectionStatus('OPEN');
        showBanner('Streaming output...', 'outline');
        currentState = 'running';
        state.retryCount = 0;
        state.isCustomReconnect = false;
    };

    state.eventSource.onerror = () => {
        state.eventSource.close();
        if (state.isCustomReconnect) return;
        state.isCustomReconnect = true;
        
        setConnectionStatus('DISCONNECTED');
        currentState = 'disconnected';
        if (ui.stateEl.innerText === 'COMPLETED' || ui.stateEl.innerText === 'FAILED') return;

        const baseDelay = 1000;
        const maxDelay = 15000;
        let exponentialDelay = Math.min(maxDelay, baseDelay * Math.pow(2, state.retryCount));
        let jitter = Math.random() * 1000;
        let finalDelay = exponentialDelay + jitter;
        
        state.retryCount++;
        showBanner(`Connection lost. Reconnecting in ${(finalDelay/1000).toFixed(1)}s... (Attempt ${state.retryCount})`, 'danger');

        setTimeout(() => {
            state.isCustomReconnect = false;
            connectSSE();
        }, finalDelay);
    };

    state.eventSource.onmessage = (e) => {
        const event = JSON.parse(e.data);
        processEvent(event, false);
    };

    state.eventSource.addEventListener('replay', (e) => {
        const event = JSON.parse(e.data);
        processEvent(event, true);
    });
}

// --- 6. BUTTON BINDINGS ---
ui.startBtn.addEventListener('click', () => {
    localStorage.removeItem('idemKey');
    localStorage.removeItem('runId');
    state.cursor = 0;
    localStorage.setItem('cursor', 0);
    state.idempotencyKey = null;
    startRun(false);
});

ui.disconnectBtn.addEventListener('click', () => {
    if (state.eventSource) {
        state.eventSource.close();
        state.isCustomReconnect = true; 
        setConnectionStatus('DISCONNECTED');
        showBanner('Manual disconnect. The server is still running!', 'danger');
        showControls(false);
        currentState = 'disconnected';
    }
});

ui.reconnectBtn.addEventListener('click', () => {
    connectSSE();
    showBanner('Reconnecting...', 'outline');
    showControls(true);
});

ui.cancelBtn.addEventListener('click', async () => {
    await fetch(`/api/runs/${state.runId}/cancel`, { method: 'POST' });
    showBanner('Cancel requested...', 'danger');
});

ui.retryPostBtn.addEventListener('click', () => {
    showBanner('Retrying POST with same key...', 'outline');
    startRun(true);
});

ui.duplicateBtn.addEventListener('click', () => {
    if (state.eventSource && state.seenEventIds.size > 0) {
        const items = ui.timeline.querySelectorAll('.timeline-item');
        if(items.length > 0) {
            const lastSeq = parseInt(items[items.length - 1].querySelector('.seq').innerText.replace('#', ''));
            const mockEvent = {
                sequence: lastSeq,
                event_id: `${state.runId}:${lastSeq}`,
                type: 'token',
                data: { text: '[DUPLICATE]' }
            };
            processEvent(mockEvent, false);
            showBanner('Simulated duplicate delivery. Check "Duplicates suppressed".', 'outline');
        }
    }
});

// CHALLENGE 3: Replay from 0
ui.replayZeroBtn.addEventListener('click', () => {
    resetUI();
    state.cursor = 0; 
    localStorage.setItem('cursor', 0);
    showBanner('Rebuilding transcript from sequence 0...', 'outline');
    connectSSE();
});

// --- 7. INITIALIZATION ---
updateTelemetry();
if (state.runId) {
    setRunState('RUNNING');
    setConnectionStatus('CONNECTING');
    showControls(true);
    connectSSE();
}