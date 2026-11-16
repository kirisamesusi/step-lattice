/**
 * SugarStep · RP2040 DDR 踏板控制器前端
 * 16 路独立压感 (4踏板×4边)、自我基线校准、0~1000 统一坐标系 1:1 同步触发线。
 */

(() => {
  'use strict';

  // =========================================================================
  // 1. 常量与默认出厂参数
  // =========================================================================
  const PAD_KEYS = ['left', 'down', 'up', 'right'];
  const SENSOR_DIRS = ['n', 's', 'w', 'e'];
  const SCALE_MAX = 999;
  const TRIG_MIN = 1;
  const TRIG_MAX = 999;
  const REL_MIN = 0;

  const DIR_META = {
    n: { label: '上侧', color: '#FF6B9E' },
    s: { label: '下侧', color: '#4CC9F0' },
    w: { label: '左侧', color: '#42E2A4' },
    e: { label: '右侧', color: '#FFB703' },
  };

  const PAD_META = {
    left:  { name: '左踏板', short: '← 左', innerDir: 'e', freq: 523.25 },
    down:  { name: '下踏板', short: '↓ 下', innerDir: 'n', freq: 587.33 },
    up:    { name: '上踏板', short: '↑ 上', innerDir: 's', freq: 659.25 },
    right: { name: '右踏板', short: '→ 右', innerDir: 'w', freq: 783.99 },
  };

  const PROFILES = {
    cotton:  { name: '轻触',   trigger: 210, release: 155, gain: 105 },
    arcade:  { name: '标准',   trigger: 360, release: 280, gain: 100 },
    pudding: { name: '防误触', trigger: 540, release: 430, gain: 95 },
  };

  const COLOR_PALETTES = {
    classic: { name: '经典糖果', left: '#FF6B9E', down: '#4CC9F0', up: '#42E2A4', right: '#FFB703' },
    macaron: { name: '马卡龙',   left: '#FF8FAB', down: '#90DBF4', up: '#95F2C6', right: '#FDE49E' },
    soda:    { name: '气泡苏打', left: '#FF758F', down: '#38BDF8', up: '#2DD4BF', right: '#A78BFA' },
    taro:    { name: '香芋奶盖', left: '#F472B6', down: '#818CF8', up: '#6EE7B7', right: '#FBBF24' },
  };

  const WAVE_POINTS = 160;
  const STORAGE_KEY = 'sugarstep_2040_v3_config';

  // =========================================================================
  // 2. 状态树
  // =========================================================================
  function createInitialPads() {
    const pads = {};
    const initBaselines = [42, 58, 49, 64, 39, 53, 61, 47, 55, 44, 67, 51, 46, 62, 57, 41];
    let ch = 0;

    for (const pk of PAD_KEYS) {
      const sensors = {};
      for (const d of SENSOR_DIRS) {
        const base = initBaselines[ch];
        sensors[d] = {
          ch,
          raw: base,
          baseline: base,
          net: 0,
          trigger: 360,
          release: 280,
          gain: 100,
          active: false,
          mouseForce: 0,
          testForce: 0,
        };
        ch += 1;
      }
      pads[pk] = {
        sensors,
        active: false,
        maxNet: 0,
        avgNet: 0,
        keyDown: false,
        mouseDown: false,
        panelTestDown: false,
        simHoldForce: 0,
        glowEnergy: 0,
      };
    }
    return pads;
  }

  const state = {
    currentView: 'sensitivity',
    sensMode: 'unified',
    oscMode: 'pad',
    profile: 'arcade',
    innerBoost: false,
    selectedPad: 'left',
    soundEnabled: true,
    wavePaused: false,
    listeningBindFor: null,
    // 无固件网页模拟测试开关（固件完成后关闭复选框或删除 HTML 中 #devSimCard 即可完全禁用）
    simTest: {
      enabled: false,
    },

    baselineCal: {
      autoDriftTrack: true,
      bootAutoCal: true,
      padLogic: 'or',
      calibrating: false,
    },

    pads: createInitialPads(),

    lighting: {
      effect: 'ripple',
      colors: { left: '#FF6B9E', down: '#4CC9F0', up: '#42E2A4', right: '#FFB703' },
      brightness: 85,
      idleBrightness: 28,
      speed: 60,
    },

    mapping: {
      hidMode: 'keyboard',
      keys: {
        left: 'ArrowLeft',
        down: 'ArrowDown',
        up: 'ArrowUp',
        right: 'ArrowRight',
        start: 'Enter',
        select: 'Shift',
      },
      pollingHz: 1000,
      debounceMs: 2.0,
    },

    waveHistory: {
      sensors: {},
      totals: { left: [], down: [], up: [], right: [] },
    },

    serial: { port: null, reader: null, connected: false, rxBuffer: '' },
  };

  for (const pk of PAD_KEYS) {
    state.waveHistory.totals[pk] = new Array(WAVE_POINTS).fill(0);
    state.waveHistory.sensors[pk] = { n: [], s: [], w: [], e: [] };
    for (const d of SENSOR_DIRS) {
      state.waveHistory.sensors[pk][d] = new Array(WAVE_POINTS).fill(0);
    }
  }

  // =========================================================================
  // 3. DOM 引用
  // =========================================================================
  const dom = {
    btnConnToggle: document.getElementById('btnConnToggle'),
    connText: document.getElementById('connText'),
    btnSoundToggle: document.getElementById('btnSoundToggle'),
    btnResetDefaults: document.getElementById('btnResetDefaults'),
    btnSaveConfig: document.getElementById('btnSaveConfig'),

    workspaceSplit: document.getElementById('workspaceSplit'),
    viewAdvanced: document.getElementById('view-advanced'),
    stageHintText: document.getElementById('stageHintText'),
    stageFocusPill: document.getElementById('stageFocusPill'),
    ledStripTrack: document.getElementById('ledStripTrack'),
    centerCoreTile: document.getElementById('centerCoreTile'),

    sensPadTitle: document.getElementById('sensPadTitle'),
    btnInnerBoost: document.getElementById('btnInnerBoost'),
    innerBoostState: document.getElementById('innerBoostState'),
    btnModeUnified: document.getElementById('btnModeUnified'),
    btnModePerEdge: document.getElementById('btnModePerEdge'),
    btnUnifiedTest: document.getElementById('btnUnifiedTest'),
    sensUnifiedBox: document.getElementById('sensUnifiedBox'),
    sensPerEdgeBox: document.getElementById('sensPerEdgeBox'),
    padTriggerBadge: document.getElementById('padTriggerBadge'),

    unifiedForceLabel: document.getElementById('unifiedForceLabel'),
    unifiedMeterFill: document.getElementById('unifiedMeterFill'),
    unifiedTriggerMarker: document.getElementById('unifiedTriggerMarker'),
    sliderUnifiedTrigger: document.getElementById('sliderUnifiedTrigger'),
    inputUnifiedTrigger: document.getElementById('inputUnifiedTrigger'),
    unifiedRuler: document.getElementById('unifiedRuler'),
    simpleEdgeList: document.getElementById('simpleEdgeList'),
    btnGoAdvanced: document.getElementById('btnGoAdvanced'),

    sliderLedBrightness: document.getElementById('sliderLedBrightness'),
    valLedBrightness: document.getElementById('valLedBrightness'),
    sliderIdleBrightness: document.getElementById('sliderIdleBrightness'),
    valIdleBrightness: document.getElementById('valIdleBrightness'),
    sliderLedSpeed: document.getElementById('sliderLedSpeed'),
    valLedSpeed: document.getElementById('valLedSpeed'),

    selectPolling: document.getElementById('selectPolling'),
    sliderDebounce: document.getElementById('sliderDebounce'),
    valDebounce: document.getElementById('valDebounce'),

    btnCalPad4: document.getElementById('btnCalPad4'),
    btnCalAll16: document.getElementById('btnCalAll16'),
    chkAutoDrift: document.getElementById('chkAutoDrift'),
    chkBootAutoCal: document.getElementById('chkBootAutoCal'),
    selectPadLogic: document.getElementById('selectPadLogic'),
    calStatusPill: document.getElementById('calStatusPill'),
    advPadTitle: document.getElementById('advPadTitle'),
    advSensorCards: document.getElementById('advSensorCards'),

    selectOscMode: document.getElementById('selectOscMode'),
    oscSubtitle: document.getElementById('oscSubtitle'),
    btnToggleWave: document.getElementById('btnToggleWave'),
    waveformCanvas: document.getElementById('fsrWaveform'),

    serialLog: document.getElementById('serialLog'),
    serialCmdInput: document.getElementById('serialCmdInput'),
    btnSendSerialCmd: document.getElementById('btnSendSerialCmd'),
    btnBootsel: document.getElementById('btnBootsel'),

    exportModal: document.getElementById('exportModal'),
    jsonConfigArea: document.getElementById('jsonConfigArea'),
    toastContainer: document.getElementById('toastContainer'),
  };

  // =========================================================================
  // 4. 音效与辅助函数
  // =========================================================================
  let audioCtx = null;

  function playCandyChime(freq, isSoft = false) {
    if (!state.soundEnabled) return;
    try {
      if (!audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        audioCtx = new AudioContextClass();
      }
      if (audioCtx.state === 'suspended') audioCtx.resume();
      const now = audioCtx.currentTime;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = isSoft ? 'sine' : 'triangle';
      osc.frequency.setValueAtTime(freq, now);
      osc.frequency.exponentialRampToValueAtTime(freq * 1.24, now + 0.05);
      gain.gain.setValueAtTime(isSoft ? 0.045 : 0.09, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now);
      osc.stop(now + 0.13);
    } catch (_) {}
  }

  let lastRulerTickMs = 0;

  function playRulerTick() {
    if (!state.soundEnabled) return;
    const nowMs = performance.now();
    if (nowMs - lastRulerTickMs < 28) return;
    lastRulerTickMs = nowMs;
    try {
      if (!audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        audioCtx = new AudioContextClass();
      }
      if (audioCtx.state === 'suspended') audioCtx.resume();
      const now = audioCtx.currentTime;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(1180, now);
      osc.frequency.exponentialRampToValueAtTime(760, now + 0.018);
      gain.gain.setValueAtTime(0.03, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.02);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now);
      osc.stop(now + 0.022);
    } catch (_) {}
  }

  function showToast(msg) {
    const toast = document.createElement('div');
    toast.className = 'candy-toast';
    toast.textContent = msg;
    dom.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(8px)';
      toast.style.transition = 'all 0.2s ease';
      setTimeout(() => toast.remove(), 210);
    }, 2200);
  }

  function appendSerialLog(text, type = 'sys') {
    const line = document.createElement('div');
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    const prefix = type === 'tx' ? '[TX]' : type === 'rx' ? '[RX]' : '[SYS]';
    line.className = `serial-line-${type}`;
    line.textContent = `${time} ${prefix} ${text}`;
    dom.serialLog.appendChild(line);
    while (dom.serialLog.children.length > 70) dom.serialLog.firstChild.remove();
    dom.serialLog.scrollTop = dom.serialLog.scrollHeight;
  }

  function hslToHex(h, s, l) {
    const a = s * Math.min(l, 1 - l);
    const f = (n) => {
      const k = (n + h / 30) % 12;
      const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
      return Math.round(255 * color).toString(16).padStart(2, '0');
    };
    return `#${f(0)}${f(8)}${f(4)}`;
  }

  function formatKeyLabel(key) {
    const map = { ArrowLeft: '←', ArrowDown: '↓', ArrowUp: '↑', ArrowRight: '→', ' ': 'Space' };
    return map[key] || key;
  }

  function getSensor(padKey, dir) {
    return state.pads[padKey].sensors[dir];
  }

  function clampTrig(val) {
    return Math.max(TRIG_MIN, Math.min(TRIG_MAX, Math.round(val)));
  }

  function clampRel(val, trig) {
    const maxRel = Math.max(0, trig - (trig > 20 ? 20 : 1));
    return Math.max(REL_MIN, Math.min(maxRel, Math.round(val)));
  }

  function snapTrigStep(val) {
    return Math.max(10, Math.min(990, Math.round(Number(val) / 10) * 10));
  }

  function snapRelStep(val, trig) {
    const stepped = Math.round(Number(val) / 10) * 10;
    const maxSteppedRel = Math.floor(Math.max(0, trig - (trig > 20 ? 20 : 1)) / 10) * 10;
    return Math.max(0, Math.min(maxSteppedRel, stepped));
  }

  function snapSimStep(val) {
    return Math.max(0, Math.min(990, Math.round(Number(val) / 10) * 10));
  }

  function highlightRulerTick(rulerEl, val) {
    if (!rulerEl) return;
    const numVal = Number(val);
    let targetLabel = null;
    if (numVal >= 980) targetLabel = 999;
    else if (Math.abs(numVal - Math.round(numVal / 100) * 100) <= 10) {
      targetLabel = Math.round(numVal / 100) * 100;
    }
    rulerEl.querySelectorAll('.ruler-num').forEach((btn) => {
      btn.classList.toggle('active-snap', Number(btn.dataset.rulerVal) === targetLabel);
    });
  }

  function toPct(val) {
    return Math.max(0, Math.min(100, (val / SCALE_MAX) * 100));
  }

  // 生成每 10 细刻度、每 50 中刻度、每 100 主刻度与数字刻度尺
  function buildRulerHTML() {
    const ticks = [];
    const labels = [];

    for (let v = 50; v < SCALE_MAX; v += 100) {
      ticks.push(`<span class="r-tick mid" style="left: ${toPct(v).toFixed(2)}%"></span>`);
    }

    const majors = [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 999];
    for (const v of majors) {
      const edgeCls = v === 0 ? ' edge-left' : v === 999 ? ' edge-right' : '';
      const pct = toPct(v).toFixed(2);
      ticks.push(`<span class="r-tick major${edgeCls}" style="left: ${pct}%"></span>`);
      labels.push(`<button type="button" class="ruler-num${edgeCls}" data-ruler-val="${v}" style="left: ${pct}%" title="点击快速设为 ${v}">${v}</button>`);
    }

    return `<div class="ruler-ticks-bar">${ticks.join('')}</div><div class="ruler-labels">${labels.join('')}</div>`;
  }

  function mountRuler(containerEl, onPickVal) {
    if (!containerEl) return;
    containerEl.innerHTML = buildRulerHTML();
    if (onPickVal) {
      containerEl.querySelectorAll('[data-ruler-val]').forEach((btn) => {
        btn.addEventListener('click', () => onPickVal(Number(btn.dataset.rulerVal)));
      });
    }
  }

  // 限制为最多 3 位纯数字，按下回车或失焦自动同步并生效
  function bindThreeDigitInput(inputEl, onCommit, getCurrentVal) {
    if (!inputEl) return;
    let skipBlur = false;

    inputEl.addEventListener('input', () => {
      const cleaned = inputEl.value.replace(/\D/g, '').slice(0, 3);
      if (inputEl.value !== cleaned) inputEl.value = cleaned;
    });

    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const rawText = inputEl.value.trim();
        if (rawText === '') {
          inputEl.value = String(getCurrentVal());
        } else {
          onCommit(Number(rawText));
        }
        skipBlur = true;
        inputEl.blur();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        inputEl.value = String(getCurrentVal());
        skipBlur = true;
        inputEl.blur();
      }
    });

    inputEl.addEventListener('blur', () => {
      if (skipBlur) {
        skipBlur = false;
        return;
      }
      const rawText = inputEl.value.trim();
      if (rawText === '') {
        inputEl.value = String(getCurrentVal());
      } else {
        onCommit(Number(rawText));
      }
    });
  }

  function updateConnectionPillUI() {
    dom.btnConnToggle.classList.remove('connected', 'sim', 'idle');
    if (state.serial.connected) {
      dom.btnConnToggle.classList.add('connected');
      dom.connText.textContent = '已连接 RP2040';
    } else if (state.simTest.enabled) {
      dom.btnConnToggle.classList.add('sim');
      dom.connText.textContent = '模拟预览中';
    } else {
      dom.btnConnToggle.classList.add('idle');
      dom.connText.textContent = '未连接 · 点击连接';
    }
  }

  function clearAllSimForces() {
    for (const pk of PAD_KEYS) {
      const pad = state.pads[pk];
      pad.mouseDown = false;
      pad.panelTestDown = false;
      pad.keyDown = false;
      pad.simHoldForce = 0;
      for (const d of SENSOR_DIRS) {
        pad.sensors[d].mouseForce = 0;
        pad.sensors[d].testForce = 0;
      }
    }
    const sliderSimHold = document.getElementById('sliderSimHold');
    const inputSimHold = document.getElementById('inputSimHold');
    if (sliderSimHold) sliderSimHold.value = '0';
    if (inputSimHold) inputSimHold.value = '0';
    highlightRulerTick(document.getElementById('simRuler'), 0);
  }

  function setSimTestEnabled(enabled) {
    const devSimCard = document.getElementById('devSimCard');
    // 若 HTML 中已删除 #devSimCard，则强制禁用所有模拟输入并进入可交付模式
    const active = Boolean(devSimCard && enabled);
    state.simTest.enabled = active;
    document.body.classList.toggle('sim-enabled', active);

    const chkSimMode = document.getElementById('chkSimMode');
    if (chkSimMode) chkSimMode.checked = active;

    const simToolsBody = document.getElementById('simToolsBody');
    if (simToolsBody) simToolsBody.classList.toggle('disabled', !active);
    const sliderSimHold = document.getElementById('sliderSimHold');
    const inputSimHold = document.getElementById('inputSimHold');
    const btnSimSinglePulse = document.getElementById('btnSimSinglePulse');
    const btnSimClearForce = document.getElementById('btnSimClearForce');
    if (sliderSimHold) sliderSimHold.disabled = !active;
    if (inputSimHold) inputSimHold.disabled = !active;
    if (btnSimSinglePulse) btnSimSinglePulse.disabled = !active;
    if (btnSimClearForce) btnSimClearForce.disabled = !active;

    if (dom.stageHintText) {
      dom.stageHintText.textContent = active
        ? '点击选踏板，按住边缘可试踩（支持方向键 / DFJK）'
        : '点击切换当前编辑踏板，连接硬件后实时显示踩踏力度';
    }

    if (!active) clearAllSimForces();
    updateConnectionPillUI();
  }

  // =========================================================================
  // 5. 视图切换与 1:1 同步 UI 渲染
  // =========================================================================
  function switchView(viewName) {
    state.currentView = viewName;
    document.querySelectorAll('.nav-pill').forEach((btn) => {
      const active = btn.dataset.view === viewName;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });

    if (viewName === 'advanced') {
      dom.workspaceSplit.hidden = true;
      dom.viewAdvanced.hidden = false;
      buildAdvancedSensorCards();
      updateOscSubtitle();
    } else {
      dom.workspaceSplit.hidden = false;
      dom.viewAdvanced.hidden = true;
      document.querySelectorAll('.view-pane').forEach((pane) => {
        pane.classList.toggle('active', pane.id === `view-${viewName}`);
      });
    }
  }

  function selectPad(padKey) {
    state.selectedPad = padKey;

    for (const pk of PAD_KEYS) {
      const padEl = document.getElementById(`pad-${pk}`);
      if (padEl) padEl.classList.toggle('selected', pk === padKey);
    }

    document.querySelectorAll('[data-select-pad]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.selectPad === padKey);
    });

    dom.stageFocusPill.textContent = PAD_META[padKey].name;
    dom.sensPadTitle.textContent = `${PAD_META[padKey].name} · 灵敏度设置`;
    dom.advPadTitle.textContent = `${PAD_META[padKey].name} · 4 颗传感器精调`;

    const simPadName = document.getElementById('simPadName');
    const sliderSimHold = document.getElementById('sliderSimHold');
    const inputSimHold = document.getElementById('inputSimHold');
    if (simPadName) simPadName.textContent = PAD_META[padKey].name;
    if (sliderSimHold) sliderSimHold.value = String(state.pads[padKey].simHoldForce || 0);
    if (inputSimHold) inputSimHold.value = String(state.pads[padKey].simHoldForce || 0);
    highlightRulerTick(document.getElementById('simRuler'), state.pads[padKey].simHoldForce || 0);

    syncUnifiedSensitivityUI();
    buildSimpleEdgeList();
    if (state.currentView === 'advanced') {
      buildAdvancedSensorCards();
      updateOscSubtitle();
    }
  }

  function syncUnifiedSensitivityUI() {
    const pad = state.pads[state.selectedPad];
    const avgTrig = Math.round(
      SENSOR_DIRS.reduce((acc, d) => acc + pad.sensors[d].trigger, 0) / 4
    );
    dom.sliderUnifiedTrigger.value = String(avgTrig);
    if (dom.inputUnifiedTrigger && document.activeElement !== dom.inputUnifiedTrigger) {
      dom.inputUnifiedTrigger.value = String(avgTrig);
    }
    dom.unifiedTriggerMarker.style.left = `${toPct(avgTrig)}%`;
    highlightRulerTick(dom.unifiedRuler, avgTrig);
  }

  function applyUnifiedTriggerValue(rawVal, { snap = false } = {}) {
    const padKey = state.selectedPad;
    const prevAvg = Math.round(
      SENSOR_DIRS.reduce((acc, d) => acc + state.pads[padKey].sensors[d].trigger, 0) / 4
    );
    const val = snap ? snapTrigStep(rawVal) : clampTrig(Number(rawVal));
    if (snap && val !== prevAvg) playRulerTick();
    const innerDir = PAD_META[padKey].innerDir;

    for (const d of SENSOR_DIRS) {
      const s = getSensor(padKey, d);
      const factor = state.innerBoost && d === innerDir ? 0.85 : 1.0;
      s.trigger = clampTrig(val * factor);
      s.release = clampRel(Math.round(s.trigger * 0.78), s.trigger);
    }

    dom.sliderUnifiedTrigger.value = String(val);
    if (dom.inputUnifiedTrigger) dom.inputUnifiedTrigger.value = String(val);
    dom.unifiedTriggerMarker.style.left = `${toPct(val)}%`;
    highlightRulerTick(dom.unifiedRuler, val);
    markCustomProfile();
    buildSimpleEdgeList();
    if (state.currentView === 'advanced') buildAdvancedSensorCards();
    sendSerialCommand(`SET:PAD_TRIG:${PAD_KEYS.indexOf(padKey)}:${val}`);
  }

  function buildSimpleEdgeList() {
    const padKey = state.selectedPad;
    const innerDir = PAD_META[padKey].innerDir;
    dom.simpleEdgeList.innerHTML = '';

    for (const d of SENSOR_DIRS) {
      const s = getSensor(padKey, d);
      const isInner = d === innerDir;
      const row = document.createElement('div');
      row.className = 'edge-row-card';
      row.innerHTML = `
        <div class="edge-row-top">
          <span class="edge-row-name">${DIR_META[d].label}${isInner ? '<span class="inner-tag">内侧边</span>' : ''}</span>
          <div class="edge-metrics-right">
            <span>力度 <strong id="simpleNet-${d}">${s.net}</strong></span>
            <span>触发</span>
            <input type="text" class="trig-num-input mini" id="simpleInput-${d}" inputmode="numeric" maxlength="3" value="${s.trigger}" aria-label="${DIR_META[d].label}触发阈值" />
          </div>
        </div>
        <div class="fused-meter-box">
          <div class="fused-bar-track compact">
            <div class="fused-bar-fill" id="simpleFill-${d}" style="width: ${toPct(s.net)}%"></div>
            <div class="fused-trig-marker" id="simpleMarker-${d}" style="left: ${toPct(s.trigger)}%"><span class="fused-trig-knob"></span></div>
            <input type="range" class="fused-range-input" data-simple-dir="${d}" min="0" max="999" value="${s.trigger}" aria-label="${DIR_META[d].label}触发滑块" />
          </div>
          <div class="fused-ruler" id="simpleRuler-${d}"></div>
        </div>
      `;

      const slider = row.querySelector('input[type="range"]');
      const numInput = row.querySelector(`#simpleInput-${d}`);
      const rulerEl = row.querySelector(`#simpleRuler-${d}`);
      const applyEdgeTrig = (rawVal, { snap = false } = {}) => {
        const prevVal = s.trigger;
        const val = snap ? snapTrigStep(rawVal) : clampTrig(Number(rawVal));
        if (snap && val !== prevVal) playRulerTick();
        s.trigger = val;
        s.release = clampRel(Math.round(val * 0.78), val);

        slider.value = String(val);
        numInput.value = String(val);
        document.getElementById(`simpleMarker-${d}`).style.left = `${toPct(val)}%`;
        highlightRulerTick(rulerEl, val);

        syncUnifiedSensitivityUI();
        if (state.currentView === 'advanced') syncAdvancedCardValues(d);
        markCustomProfile();
        sendSerialCommand(`SET:FSR:${s.ch}:${s.trigger}:${s.release}:${s.gain}`);
      };

      slider.addEventListener('input', (e) => applyEdgeTrig(e.target.value, { snap: true }));
      bindThreeDigitInput(numInput, (v) => applyEdgeTrig(v, { snap: false }), () => s.trigger);
      mountRuler(rulerEl, (v) => applyEdgeTrig(v, { snap: false }));
      highlightRulerTick(rulerEl, s.trigger);

      dom.simpleEdgeList.appendChild(row);
    }
  }

  function buildAdvancedSensorCards() {
    const pk = state.selectedPad;
    const innerDir = PAD_META[pk].innerDir;
    dom.advSensorCards.innerHTML = '';

    for (const d of SENSOR_DIRS) {
      const s = getSensor(pk, d);
      const isInner = d === innerDir;
      const card = document.createElement('div');
      card.className = `adv-sensor-card${s.active ? ' hit' : ''}`;
      card.id = `advCard-${d}`;
      card.innerHTML = `
        <div class="adv-card-head">
          <div class="adv-card-title">
            <span class="adv-dir-dot" style="background:${DIR_META[d].color}"></span>
            <span>${PAD_META[pk].name} · ${DIR_META[d].label}</span>
            ${isInner ? '<span class="inner-tag">内侧边</span>' : ''}
          </div>
          <div class="adv-card-actions">
            <button type="button" class="mini-action-btn sim-only" data-adv-test="${d}">按住试压</button>
            <button type="button" class="mini-action-btn cal" data-adv-cal="${d}">校准基线</button>
          </div>
        </div>

        <div class="adv-readouts">
          <div class="adv-chip-group">
            <span class="adv-chip" id="advRaw-${d}">原 ${Math.round(s.raw)}</span>
            <span class="adv-chip" id="advBase-${d}">基 ${Math.round(s.baseline)}</span>
            <span class="adv-chip net" id="advNet-${d}">净 ${s.net}</span>
          </div>
          <span class="live-status-badge${s.active ? ' active' : ''}" id="advState-${d}">${s.active ? '已触发' : '未触发'}</span>
        </div>

        <div class="aligned-track-pad">
          <div class="adv-dual-meter">
            <div class="adv-dual-fill" id="advFill-${d}" style="width: ${toPct(s.net)}%"></div>
            <div class="adv-line-rel" id="advLineRel-${d}" style="left: ${toPct(s.release)}%"></div>
            <div class="adv-line-trig" id="advLineTrig-${d}" style="left: ${toPct(s.trigger)}%"></div>
          </div>
          <div class="fused-ruler" id="advRuler-${d}"></div>
        </div>

        <div class="adv-sliders-stack">
          <div class="adv-slider-row">
            <div class="adv-slider-top">
              <span>触发阈值 (红线)</span>
              <input type="text" class="trig-num-input mini" id="advTrigInput-${d}" inputmode="numeric" maxlength="3" value="${s.trigger}" aria-label="${DIR_META[d].label}触发阈值" />
            </div>
            <div class="full-slider-wrap">
              <div class="full-slider-track"></div>
              <input type="range" class="candy-range full-range" data-adv="trigger" min="0" max="999" value="${s.trigger}" />
            </div>
          </div>
          <div class="adv-slider-row">
            <div class="adv-slider-top">
              <span>释放回差 (蓝线)</span>
              <input type="text" class="trig-num-input mini blue" id="advRelInput-${d}" inputmode="numeric" maxlength="3" value="${s.release}" aria-label="${DIR_META[d].label}释放回差" />
            </div>
            <div class="full-slider-wrap">
              <div class="full-slider-track"></div>
              <input type="range" class="candy-range range-blue full-range" data-adv="release" min="0" max="999" value="${s.release}" />
            </div>
          </div>
          <div class="adv-slider-row">
            <div class="adv-slider-top"><span>信号增益</span><strong id="advGainTxt-${d}">${s.gain}%</strong></div>
            <div class="full-slider-wrap">
              <div class="full-slider-track"></div>
              <input type="range" class="candy-range range-lilac full-range" data-adv="gain" min="50" max="150" value="${s.gain}" />
            </div>
          </div>
        </div>
      `;

      const trigSlider = card.querySelector('[data-adv="trigger"]');
      const relSlider = card.querySelector('[data-adv="release"]');
      const gainSlider = card.querySelector('[data-adv="gain"]');
      const trigInput = card.querySelector(`#advTrigInput-${d}`);
      const relInput = card.querySelector(`#advRelInput-${d}`);
      const advRulerEl = card.querySelector(`#advRuler-${d}`);

      const applyAdvTrigger = (rawVal, { snap = false } = {}) => {
        const prevVal = s.trigger;
        const val = snap ? snapTrigStep(rawVal) : clampTrig(Number(rawVal));
        if (snap && val !== prevVal) playRulerTick();
        s.trigger = val;
        trigSlider.value = String(val);
        trigInput.value = String(val);

        if (s.release >= val - (val > 20 ? 20 : 1)) {
          s.release = clampRel(Math.round(val * 0.78), val);
          relSlider.value = String(s.release);
          relInput.value = String(s.release);
          document.getElementById(`advLineRel-${d}`).style.left = `${toPct(s.release)}%`;
        }
        document.getElementById(`advLineTrig-${d}`).style.left = `${toPct(val)}%`;
        highlightRulerTick(advRulerEl, val);

        syncUnifiedSensitivityUI();
        buildSimpleEdgeList();
        markCustomProfile();
        sendSerialCommand(`SET:FSR:${s.ch}:${s.trigger}:${s.release}:${s.gain}`);
      };

      const applyAdvRelease = (rawVal, { snap = false } = {}) => {
        const prevVal = s.release;
        const val = snap ? snapRelStep(rawVal, s.trigger) : clampRel(Number(rawVal), s.trigger);
        if (snap && val !== prevVal) playRulerTick();
        s.release = val;
        relSlider.value = String(val);
        relInput.value = String(val);
        document.getElementById(`advLineRel-${d}`).style.left = `${toPct(val)}%`;
        sendSerialCommand(`SET:FSR:${s.ch}:${s.trigger}:${s.release}:${s.gain}`);
      };

      trigSlider.addEventListener('input', (e) => applyAdvTrigger(e.target.value, { snap: true }));
      relSlider.addEventListener('input', (e) => applyAdvRelease(e.target.value, { snap: true }));
      bindThreeDigitInput(trigInput, (v) => applyAdvTrigger(v, { snap: false }), () => s.trigger);
      bindThreeDigitInput(relInput, (v) => applyAdvRelease(v, { snap: false }), () => s.release);
      mountRuler(advRulerEl, (v) => applyAdvTrigger(v, { snap: false }));
      highlightRulerTick(advRulerEl, s.trigger);

      gainSlider.addEventListener('input', (e) => {
        s.gain = Number(e.target.value);
        document.getElementById(`advGainTxt-${d}`).textContent = `${s.gain}%`;
        sendSerialCommand(`SET:FSR:${s.ch}:${s.trigger}:${s.release}:${s.gain}`);
      });

      const testBtn = card.querySelector(`[data-adv-test="${d}"]`);
      if (testBtn) {
        testBtn.addEventListener('pointerdown', () => {
          if (!state.simTest.enabled) return;
          s.testForce = 760;
        });
        const releaseTest = () => { s.testForce = 0; };
        testBtn.addEventListener('pointerup', releaseTest);
        testBtn.addEventListener('pointerleave', releaseTest);
        testBtn.addEventListener('pointercancel', releaseTest);
      }

      card.querySelector(`[data-adv-cal="${d}"]`).addEventListener('click', () => {
        s.baseline = Math.max(0, Math.min(500, Math.round(s.raw)));
        document.getElementById(`advBase-${d}`).textContent = `基 ${s.baseline}`;
        sendSerialCommand(`CMD:CAL_BASE:CH:${s.ch}`);
        showToast(`已校准 ${PAD_META[pk].name}·${DIR_META[d].label} 基线`);
      });

      dom.advSensorCards.appendChild(card);
    }
  }

  function syncAdvancedCardValues(dir) {
    const card = document.getElementById(`advCard-${dir}`);
    if (!card) return;
    const s = getSensor(state.selectedPad, dir);
    card.querySelector('[data-adv="trigger"]').value = String(s.trigger);
    card.querySelector('[data-adv="release"]').value = String(s.release);
    card.querySelector('[data-adv="gain"]').value = String(s.gain);
    const trigInput = document.getElementById(`advTrigInput-${dir}`);
    const relInput = document.getElementById(`advRelInput-${dir}`);
    if (trigInput && document.activeElement !== trigInput) trigInput.value = String(s.trigger);
    if (relInput && document.activeElement !== relInput) relInput.value = String(s.release);
    document.getElementById(`advGainTxt-${dir}`).textContent = `${s.gain}%`;
    document.getElementById(`advLineTrig-${dir}`).style.left = `${toPct(s.trigger)}%`;
    document.getElementById(`advLineRel-${dir}`).style.left = `${toPct(s.release)}%`;
    highlightRulerTick(document.getElementById(`advRuler-${dir}`), s.trigger);
  }

  function updateOscSubtitle() {
    dom.oscSubtitle.textContent = state.oscMode === 'all'
      ? '显示四块踏板的最大净压力曲线'
      : `显示${PAD_META[state.selectedPad].name} 4 颗传感器的实时净压力曲线`;
  }

  // =========================================================================
  // 6. 灯光、映射、预设与「恢复默认」
  // =========================================================================
  function initLedStripBeads() {
    dom.ledStripTrack.innerHTML = '';
    for (let i = 0; i < 16; i += 1) {
      const bead = document.createElement('span');
      bead.className = 'led-bead';
      dom.ledStripTrack.appendChild(bead);
    }
  }

  function applyColorsToCss() {
    const root = document.documentElement;
    for (const k of PAD_KEYS) {
      root.style.setProperty(`--pad-${k}`, state.lighting.colors[k]);
      const picker = document.getElementById(`color-${k}`);
      if (picker) picker.value = state.lighting.colors[k];
    }
  }

  function syncLightingUI() {
    document.querySelectorAll('.effect-card').forEach((card) => {
      card.classList.toggle('active', card.dataset.effect === state.lighting.effect);
    });
    dom.sliderLedBrightness.value = state.lighting.brightness;
    dom.valLedBrightness.textContent = `${state.lighting.brightness}%`;
    dom.sliderIdleBrightness.value = state.lighting.idleBrightness;
    dom.valIdleBrightness.textContent = `${state.lighting.idleBrightness}%`;
    dom.sliderLedSpeed.value = state.lighting.speed;
    dom.valLedSpeed.textContent = `${state.lighting.speed}%`;
    applyColorsToCss();
  }

  function syncMappingUI() {
    document.querySelectorAll('#hidModePills .seg-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.hid === state.mapping.hidMode);
    });

    const dfjkHints = { left: 'D', down: 'F', up: 'J', right: 'K' };
    for (const k of PAD_KEYS) {
      const keyVal = state.mapping.keys[k];
      const padBadge = document.getElementById(`padKey-${k}`);
      const bindBtn = document.getElementById(`bindBtn-${k}`);
      if (padBadge) padBadge.textContent = `${formatKeyLabel(keyVal)} / ${dfjkHints[k]}`;
      if (bindBtn) bindBtn.textContent = keyVal;
    }

    document.getElementById('bindBtn-start').textContent = state.mapping.keys.start;
    document.getElementById('bindBtn-select').textContent = state.mapping.keys.select;

    dom.selectPolling.value = String(state.mapping.pollingHz);
    dom.sliderDebounce.value = String(state.mapping.debounceMs);
    dom.valDebounce.textContent = `${Number(state.mapping.debounceMs).toFixed(1)} ms`;
  }

  function applyProfile(profileKey, silent = false) {
    state.profile = profileKey;
    document.querySelectorAll('.preset-chip').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.profile === profileKey);
    });
    const p = PROFILES[profileKey];
    if (!p) return;

    for (const pk of PAD_KEYS) {
      const innerDir = PAD_META[pk].innerDir;
      for (const d of SENSOR_DIRS) {
        const s = getSensor(pk, d);
        const boostFactor = state.innerBoost && d === innerDir ? 0.85 : 1.0;
        s.trigger = clampTrig(p.trigger * boostFactor);
        s.release = clampRel(p.release * boostFactor, s.trigger);
        s.gain = state.innerBoost && d === innerDir ? 115 : p.gain;
      }
    }

    syncUnifiedSensitivityUI();
    buildSimpleEdgeList();
    if (state.currentView === 'advanced') buildAdvancedSensorCards();
    if (!silent) {
      sendSerialCommand(`SET:PROFILE:${profileKey.toUpperCase()}`);
      showToast(`已切换至「${p.name}」模式`);
    }
  }

  function markCustomProfile() {
    state.profile = 'custom';
    document.querySelectorAll('.preset-chip').forEach((btn) => {
      btn.classList.remove('active');
    });
  }

  function toggleInnerBoost() {
    state.innerBoost = !state.innerBoost;
    dom.btnInnerBoost.classList.toggle('active', state.innerBoost);
    dom.innerBoostState.textContent = state.innerBoost ? '开' : '关';

    for (const pk of PAD_KEYS) {
      const innerDir = PAD_META[pk].innerDir;
      const innerS = getSensor(pk, innerDir);
      const refDir = innerDir === 'e' ? 'w' : innerDir === 'w' ? 'e' : innerDir === 'n' ? 's' : 'n';
      const refS = getSensor(pk, refDir);
      if (state.innerBoost) {
        innerS.trigger = clampTrig(refS.trigger * 0.85);
        innerS.release = clampRel(refS.release * 0.85, innerS.trigger);
        innerS.gain = 115;
      } else {
        innerS.trigger = refS.trigger;
        innerS.release = refS.release;
        innerS.gain = 100;
      }
    }

    syncUnifiedSensitivityUI();
    buildSimpleEdgeList();
    if (state.currentView === 'advanced') buildAdvancedSensorCards();
    sendSerialCommand(`SET:INNER_BOOST:${state.innerBoost ? 1 : 0}`);
    showToast(state.innerBoost ? '已开启内侧边增敏' : '已恢复四边均衡触发');
  }

  function isConfigModified() {
    if (state.innerBoost) return true;

    for (const pk of PAD_KEYS) {
      for (const d of SENSOR_DIRS) {
        const s = getSensor(pk, d);
        if (s.trigger !== 360 || s.release !== 280 || s.gain !== 100) return true;
      }
    }

    const bc = state.baselineCal;
    if (!bc.autoDriftTrack || !bc.bootAutoCal || bc.padLogic !== 'or') return true;

    const l = state.lighting;
    if (l.effect !== 'ripple' || l.brightness !== 85 || l.idleBrightness !== 28 || l.speed !== 60) return true;
    for (const pk of PAD_KEYS) {
      if (String(l.colors[pk]).toUpperCase() !== COLOR_PALETTES.classic[pk].toUpperCase()) return true;
    }

    const m = state.mapping;
    if (m.hidMode !== 'keyboard' || m.pollingHz !== 1000 || Number(m.debounceMs) !== 2.0) return true;
    const defKeys = { left: 'ArrowLeft', down: 'ArrowDown', up: 'ArrowUp', right: 'ArrowRight', start: 'Enter', select: 'Shift' };
    for (const k of Object.keys(defKeys)) {
      if (m.keys[k] !== defKeys[k]) return true;
    }

    return false;
  }

  function resetAllDefaults() {
    state.innerBoost = false;
    dom.btnInnerBoost.classList.remove('active');
    dom.innerBoostState.textContent = '关';

    state.lighting = {
      effect: 'ripple',
      colors: { ...COLOR_PALETTES.classic },
      brightness: 85,
      idleBrightness: 28,
      speed: 60,
    };
    delete state.lighting.name;

    state.mapping = {
      hidMode: 'keyboard',
      keys: {
        left: 'ArrowLeft',
        down: 'ArrowDown',
        up: 'ArrowUp',
        right: 'ArrowRight',
        start: 'Enter',
        select: 'Shift',
      },
      pollingHz: 1000,
      debounceMs: 2.0,
    };

    state.baselineCal.autoDriftTrack = true;
    state.baselineCal.bootAutoCal = true;
    state.baselineCal.padLogic = 'or';
    dom.chkAutoDrift.checked = true;
    dom.chkBootAutoCal.checked = true;
    dom.selectPadLogic.value = 'or';

    applyProfile('arcade', true);
    syncLightingUI();
    syncMappingUI();
    clearAllSimForces();

    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    sendSerialCommand('CMD:RESET_DEFAULTS');
    showToast('已恢复为默认设置');
  }

  // =========================================================================
  // 7. 自我基线校准
  // =========================================================================
  function calibrateSensors(padKey = null) {
    if (state.baselineCal.calibrating) return;
    state.baselineCal.calibrating = true;
    dom.calStatusPill.textContent = '基线状态：校准中...';

    setTimeout(() => {
      const targetPads = padKey ? [padKey] : PAD_KEYS;
      for (const pk of targetPads) {
        for (const d of SENSOR_DIRS) {
          const s = getSensor(pk, d);
          s.baseline = Math.max(0, Math.min(500, Math.round(s.raw)));
        }
      }
      state.baselineCal.calibrating = false;
      dom.calStatusPill.textContent = '基线状态：已锁定 16/16';
      if (state.currentView === 'advanced') buildAdvancedSensorCards();
      sendSerialCommand(padKey ? `CMD:CAL_BASE:PAD:${PAD_KEYS.indexOf(padKey)}` : 'CMD:CAL_BASE:ALL');
      showToast(padKey ? `已完成${PAD_META[padKey].name}基线校准` : '已完成全部 16 颗基线校准');
    }, 360);
  }

  // =========================================================================
  // 8. 舞台光效与 60fps 示波器
  // =========================================================================
  function triggerPadEffects(padKey) {
    const pad = state.pads[padKey];
    pad.active = true;
    pad.glowEnergy = 1.0;

    const padEl = document.getElementById(`pad-${padKey}`);
    if (padEl) {
      padEl.classList.remove('rippling');
      void padEl.offsetWidth;
      padEl.classList.add('rippling');
    }

    dom.centerCoreTile.classList.remove('bouncing');
    void dom.centerCoreTile.offsetWidth;
    dom.centerCoreTile.classList.add('bouncing');
    setTimeout(() => dom.centerCoreTile.classList.remove('bouncing'), 160);

    playCandyChime(PAD_META[padKey].freq);
  }

  function updateLightingPreview(nowSec) {
    const { effect, colors, brightness, idleBrightness, speed } = state.lighting;
    const speedFactor = 0.6 + (speed / 100) * 2.4;
    const beads = dom.ledStripTrack.children;
    const brightScale = brightness / 100;
    const idleScale = idleBrightness / 100;

    PAD_KEYS.forEach((k, idx) => {
      const pad = state.pads[k];
      const padEl = document.getElementById(`pad-${k}`);
      if (!padEl) return;

      if (!pad.active && pad.glowEnergy > 0) {
        const decay = effect === 'afterglow' ? 0.02 : 0.055;
        pad.glowEnergy = Math.max(0, pad.glowEnergy - decay);
      }

      let padOpacity = idleScale;
      let dynamicColor = colors[k];

      if (effect === 'rainbow') {
        const hue = ((nowSec * 65 * speedFactor) + idx * 75) % 360;
        dynamicColor = hslToHex(hue, 0.9, 0.62);
        padOpacity = Math.max(idleScale, 0.45 * brightScale);
      } else if (effect === 'breathe') {
        const wave = 0.5 + 0.5 * Math.sin(nowSec * 2.2 * speedFactor + idx * 0.4);
        padOpacity = idleScale * (0.45 + 0.55 * wave);
      } else if (effect === 'afterglow') {
        padOpacity = pad.glowEnergy * brightScale;
      } else if (effect === 'solid') {
        padOpacity = Math.max(0.35, idleScale) * brightScale;
      } else {
        padOpacity = Math.max(idleScale, pad.glowEnergy * brightScale);
      }

      if (pad.active) padOpacity = Math.max(0.75, brightScale);
      padEl.style.setProperty('--pad-color', dynamicColor);
      padEl.style.setProperty('--pad-idle-opacity', padOpacity.toFixed(2));
    });

    const anyActive = PAD_KEYS.some((k) => state.pads[k].active);
    const activeColors = PAD_KEYS.filter((k) => state.pads[k].active).map((k) => state.lighting.colors[k]);

    for (let i = 0; i < beads.length; i += 1) {
      const bead = beads[i];
      let c = colors[PAD_KEYS[i % 4]];
      let op = Math.max(0.2, idleScale);

      if (effect === 'rainbow' && !anyActive) {
        const hue = ((nowSec * 90 * speedFactor) + i * 20) % 360;
        c = hslToHex(hue, 0.92, 0.64);
        op = Math.max(0.35, brightScale * 0.85);
      } else if (effect === 'breathe' && !anyActive) {
        op = 0.2 + (0.5 + 0.5 * Math.sin(nowSec * 2.4 * speedFactor)) * 0.5;
      }
      if (anyActive) {
        c = activeColors[i % activeColors.length];
        op = Math.max(0.75, brightScale);
      }
      bead.style.backgroundColor = c;
      bead.style.color = c;
      bead.style.opacity = op.toFixed(2);
    }
  }

  function drawWaveform() {
    if (state.currentView !== 'advanced') return;
    const canvas = dom.waveformCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const targetW = Math.max(300, Math.floor(rect.width * dpr));
    const targetH = Math.max(110, Math.floor(rect.height * dpr));

    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = 'rgba(255, 182, 213, 0.35)';
    ctx.lineWidth = 1 * dpr;
    for (let row = 1; row <= 3; row += 1) {
      const y = (h / 4) * row;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // 参考触发线与释放线
    const pad = state.pads[state.selectedPad];
    const avgTrig = SENSOR_DIRS.reduce((acc, d) => acc + pad.sensors[d].trigger, 0) / 4;
    const avgRel = SENSOR_DIRS.reduce((acc, d) => acc + pad.sensors[d].release, 0) / 4;
    const trigY = h - (avgTrig / SCALE_MAX) * (h - 10 * dpr) - 5 * dpr;
    const relY = h - (avgRel / SCALE_MAX) * (h - 10 * dpr) - 5 * dpr;

    ctx.save();
    ctx.setLineDash([6 * dpr, 5 * dpr]);
    ctx.lineWidth = 1.5 * dpr;
    ctx.strokeStyle = 'rgba(230, 46, 107, 0.72)';
    ctx.beginPath();
    ctx.moveTo(0, trigY);
    ctx.lineTo(w, trigY);
    ctx.stroke();

    ctx.strokeStyle = 'rgba(40, 132, 216, 0.65)';
    ctx.beginPath();
    ctx.moveTo(0, relY);
    ctx.lineTo(w, relY);
    ctx.stroke();
    ctx.restore();

    if (state.oscMode === 'all') {
      for (const pk of PAD_KEYS) {
        const hist = state.waveHistory.totals[pk];
        ctx.strokeStyle = state.lighting.colors[pk];
        ctx.lineWidth = 2.2 * dpr;
        ctx.beginPath();
        for (let i = 0; i < hist.length; i += 1) {
          const x = (i / (hist.length - 1)) * w;
          const y = h - (Math.min(SCALE_MAX, hist[i]) / SCALE_MAX) * (h - 10 * dpr) - 5 * dpr;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
    } else {
      const target = state.selectedPad;
      for (const d of SENSOR_DIRS) {
        const hist = state.waveHistory.sensors[target][d];
        ctx.strokeStyle = DIR_META[d].color;
        ctx.lineWidth = 2.2 * dpr;
        ctx.beginPath();
        for (let i = 0; i < hist.length; i += 1) {
          const x = (i / (hist.length - 1)) * w;
          const y = h - (Math.min(SCALE_MAX, hist[i]) / SCALE_MAX) * (h - 10 * dpr) - 5 * dpr;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
    }
  }

  // =========================================================================
  // 9. 主循环 (60fps 模拟、实时同步与界面刷新)
  // =========================================================================
  let lastSlowRefresh = 0;

  function mainLoop(nowMs) {
    const refreshSlow = nowMs - lastSlowRefresh > 80;
    if (refreshSlow) lastSlowRefresh = nowMs;

    for (const pk of PAD_KEYS) {
      const pad = state.pads[pk];
      let maxNet = 0;
      let sumNet = 0;
      let anySensorActive = false;

      for (const d of SENSOR_DIRS) {
        const s = pad.sensors[d];
        const panelTestForce = pad.panelTestDown ? 780 : 0;
        const holdForce = pad.simHoldForce || 0;
        const keyForce = pad.keyDown ? (d === PAD_META[pk].innerDir ? 760 : 620) : 0;

        if (!state.serial.connected) {
          if (state.simTest.enabled) {
            const force = Math.max(s.mouseForce, s.testForce, panelTestForce, holdForce, keyForce);
            const jitter = (Math.random() - 0.5) * 6;
            const desired = Math.max(0, Math.min(1023, s.baseline + force + jitter));
            s.raw += (desired - s.raw) * 0.45;
          } else {
            // 关闭模拟测试或删除模拟模块后，读数平滑回落到静态基线
            const baseDiff = s.baseline - s.raw;
            s.raw = Math.abs(baseDiff) < 0.4 ? s.baseline : s.raw + baseDiff * 0.35;
          }
        }

        if (
          state.baselineCal.autoDriftTrack &&
          (state.serial.connected || state.simTest.enabled) &&
          !s.active &&
          s.mouseForce === 0 &&
          s.testForce === 0 &&
          !pad.panelTestDown &&
          !pad.keyDown &&
          holdForce === 0
        ) {
          const diff = s.raw - s.baseline;
          if (Math.abs(diff) < 25) s.baseline += diff * 0.015;
        }

        const net = Math.max(0, Math.min(SCALE_MAX, Math.round((s.raw - s.baseline) * (s.gain / 100))));
        s.net = net;
        if (net > maxNet) maxNet = net;
        sumNet += net;

        if (!s.active && net >= s.trigger) s.active = true;
        else if (s.active && net <= s.release) s.active = false;
        if (s.active) anySensorActive = true;

        const edgeBar = document.getElementById(`edgeBar-${pk}-${d}`);
        if (edgeBar) {
          edgeBar.classList.toggle('press', net > 45 && !s.active);
          edgeBar.classList.toggle('hit', s.active);
        }

        if (!state.wavePaused) {
          state.waveHistory.sensors[pk][d].push(net);
          if (state.waveHistory.sensors[pk][d].length > WAVE_POINTS) state.waveHistory.sensors[pk][d].shift();
        }

        // 高级页当前踏板 4 张卡片实时压力条与数字同步
        if (state.currentView === 'advanced' && pk === state.selectedPad) {
          const fillEl = document.getElementById(`advFill-${d}`);
          if (fillEl) fillEl.style.width = `${toPct(net)}%`;

          if (refreshSlow) {
            const card = document.getElementById(`advCard-${d}`);
            if (card) {
              card.classList.toggle('hit', s.active);
              document.getElementById(`advRaw-${d}`).textContent = `原 ${Math.round(s.raw)}`;
              document.getElementById(`advBase-${d}`).textContent = `基 ${Math.round(s.baseline)}`;
              document.getElementById(`advNet-${d}`).textContent = `净 ${net}`;
              const st = document.getElementById(`advState-${d}`);
              st.textContent = s.active ? '已触发' : '未触发';
              st.classList.toggle('active', s.active);
            }
          }
        }
      }

      pad.maxNet = maxNet;
      pad.avgNet = Math.round(sumNet / 4);

      let wantsActive = anySensorActive;
      if (state.baselineCal.padLogic === 'avg') {
        const avgTrig = SENSOR_DIRS.reduce((acc, d) => acc + pad.sensors[d].trigger, 0) / 4;
        const avgRel = SENSOR_DIRS.reduce((acc, d) => acc + pad.sensors[d].release, 0) / 4;
        wantsActive = pad.active ? pad.avgNet > avgRel : pad.avgNet >= avgTrig;
      }

      if (!pad.active && wantsActive) triggerPadEffects(pk);
      else if (pad.active && !wantsActive) pad.active = false;

      const padEl = document.getElementById(`pad-${pk}`);
      if (padEl) padEl.classList.toggle('active', pad.active);

      if (!state.wavePaused) {
        state.waveHistory.totals[pk].push(maxNet);
        if (state.waveHistory.totals[pk].length > WAVE_POINTS) state.waveHistory.totals[pk].shift();
      }
    }

    // 灵敏度页实时压力条同步 (统一 0~1000 刻度)
    if (state.currentView === 'sensitivity') {
      const selPad = state.pads[state.selectedPad];
      const displayVal = state.baselineCal.padLogic === 'avg' ? selPad.avgNet : selPad.maxNet;
      dom.unifiedForceLabel.textContent = String(displayVal);
      dom.unifiedMeterFill.style.width = `${toPct(displayVal)}%`;
      dom.padTriggerBadge.textContent = selPad.active ? '已触发' : '未踩下';
      dom.padTriggerBadge.classList.toggle('active', selPad.active);

      for (const d of SENSOR_DIRS) {
        const net = selPad.sensors[d].net;
        const dotEl = document.getElementById(`dotVal-${d}`);
        if (dotEl) dotEl.textContent = String(net);

        if (state.sensMode === 'per-edge') {
          const fill = document.getElementById(`simpleFill-${d}`);
          const read = document.getElementById(`simpleNet-${d}`);
          if (fill) fill.style.width = `${toPct(net)}%`;
          if (read) read.textContent = String(net);
        }
      }
    }

    updateLightingPreview(nowMs / 1000);
    if (!state.wavePaused) drawWaveform();

    requestAnimationFrame(mainLoop);
  }

  // =========================================================================
  // 10. WebSerial 串口连接与本地存储
  // =========================================================================
  async function toggleSerialConnection() {
    if (state.serial.connected) {
      await disconnectSerial();
      return;
    }
    if (!('serial' in navigator)) {
      showToast('当前浏览器不支持网页直连，请使用新版 Chrome 或 Edge');
      return;
    }
    try {
      const port = await navigator.serial.requestPort();
      await port.open({ baudRate: 115200 });
      state.serial.port = port;
      state.serial.connected = true;
      updateConnectionPillUI();
      readSerialLoop(port);
      sendSerialCommand('GET:CFG');
      showToast('已连接到控制器');
    } catch (err) {
      appendSerialLog(`连接取消: ${err.message}`, 'sys');
    }
  }

  async function disconnectSerial() {
    if (state.serial.reader) { try { await state.serial.reader.cancel(); } catch (_) {} state.serial.reader = null; }
    if (state.serial.port) { try { await state.serial.port.close(); } catch (_) {} state.serial.port = null; }
    state.serial.connected = false;
    updateConnectionPillUI();
    showToast(state.simTest.enabled ? '已切换回模拟预览' : '已断开控制器连接');
  }

  async function readSerialLoop(port) {
    const decoder = new TextDecoderStream();
    port.readable.pipeTo(decoder.writable);
    const reader = decoder.readable.getReader();
    state.serial.reader = reader;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) {
          state.serial.rxBuffer += value;
          const lines = state.serial.rxBuffer.split(/\r?\n/);
          state.serial.rxBuffer = lines.pop() || '';
          for (const line of lines) {
            if (line.trim()) handleIncomingSerial(line.trim());
          }
        }
      }
    } catch (_) {
      disconnectSerial();
    }
  }

  function handleIncomingSerial(line) {
    if (line.startsWith('FSR16:')) {
      const parts = line.slice(6).split(',').map((v) => Number(v.trim()));
      if (parts.length === 16 && parts.every((n) => !Number.isNaN(n))) {
        let idx = 0;
        for (const pk of PAD_KEYS) for (const d of SENSOR_DIRS) {
          state.pads[pk].sensors[d].raw = Math.max(0, Math.min(1023, parts[idx++]));
        }
      }
      return;
    }
    appendSerialLog(line, 'rx');
  }

  async function sendSerialCommand(cmd) {
    appendSerialLog(cmd, 'tx');
    if (state.serial.connected && state.serial.port && state.serial.port.writable) {
      try {
        const writer = state.serial.port.writable.getWriter();
        await writer.write(new TextEncoder().encode(`${cmd}\n`));
        writer.releaseLock();
      } catch (_) {}
    } else if (state.simTest.enabled) {
      setTimeout(() => appendSerialLog(`OK:${cmd}`, 'rx'), 40);
    }
  }

  function exportConfigObject() {
    const sensors16 = [];
    for (const pk of PAD_KEYS) {
      for (const d of SENSOR_DIRS) {
        const s = getSensor(pk, d);
        sensors16.push({ ch: s.ch, pad: pk, dir: d, baseline: Math.round(s.baseline), trigger: s.trigger, release: s.release, gain: s.gain });
      }
    }
    return { schema: 'sugarstep-rp2040-v3', profile: state.profile, innerBoost: state.innerBoost, baselineCal: state.baselineCal, sensors16, lighting: state.lighting, mapping: state.mapping };
  }

  function importConfigObject(cfg) {
    if (!cfg || typeof cfg !== 'object') throw new Error('JSON 格式不正确');
    if (Array.isArray(cfg.sensors16)) {
      for (const item of cfg.sensors16) {
        if (PAD_KEYS.includes(item.pad) && SENSOR_DIRS.includes(item.dir)) {
          const s = getSensor(item.pad, item.dir);
          if (item.baseline !== undefined) s.baseline = Number(item.baseline);
          if (item.trigger !== undefined) s.trigger = clampTrig(Number(item.trigger));
          if (item.release !== undefined) s.release = clampRel(Number(item.release), s.trigger);
          if (item.gain !== undefined) s.gain = Number(item.gain);
        }
      }
    }
    if (cfg.baselineCal) {
      Object.assign(state.baselineCal, cfg.baselineCal);
      dom.chkAutoDrift.checked = Boolean(state.baselineCal.autoDriftTrack);
      dom.chkBootAutoCal.checked = Boolean(state.baselineCal.bootAutoCal);
      dom.selectPadLogic.value = state.baselineCal.padLogic || 'or';
    }
    if (cfg.lighting) {
      Object.assign(state.lighting, cfg.lighting);
      if (cfg.lighting.colors) Object.assign(state.lighting.colors, cfg.lighting.colors);
    }
    if (cfg.mapping) {
      Object.assign(state.mapping, cfg.mapping);
      if (cfg.mapping.keys) Object.assign(state.mapping.keys, cfg.mapping.keys);
    }
    if (cfg.innerBoost !== undefined) {
      state.innerBoost = Boolean(cfg.innerBoost);
      dom.btnInnerBoost.classList.toggle('active', state.innerBoost);
      dom.innerBoostState.textContent = state.innerBoost ? '开' : '关';
    }
    selectPad(state.selectedPad);
    syncLightingUI();
    syncMappingUI();
  }

  function saveAllConfig() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(exportConfigObject())); } catch (_) {}
    sendSerialCommand('SAVE:FLASH');
    showToast('设置已保存');
  }

  function loadSavedConfig() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) importConfigObject(JSON.parse(saved));
    } catch (_) {}
  }

  // =========================================================================
  // 11. 事件绑定
  // =========================================================================
  function updatePadPointerForce(padKey, clientX, clientY) {
    const padEl = document.getElementById(`pad-${padKey}`);
    if (!padEl) return;
    const rect = padEl.getBoundingClientRect();
    const nx = Math.max(-1, Math.min(1, ((clientX - rect.left) / rect.width - 0.5) * 2));
    const ny = Math.max(-1, Math.min(1, ((clientY - rect.top) / rect.height - 0.5) * 2));

    const weights = {
      n: Math.max(0.2, 0.58 - ny * 0.55),
      s: Math.max(0.2, 0.58 + ny * 0.55),
      w: Math.max(0.2, 0.58 - nx * 0.55),
      e: Math.max(0.2, 0.58 + nx * 0.55),
    };
    for (const d of SENSOR_DIRS) getSensor(padKey, d).mouseForce = Math.round(weights[d] * 820);
    if (state.selectedPad !== padKey) selectPad(padKey);
  }

  function clearPadPointerForce(padKey) {
    state.pads[padKey].mouseDown = false;
    for (const d of SENSOR_DIRS) getSensor(padKey, d).mouseForce = 0;
  }

  function bindEvents() {
    document.querySelectorAll('.nav-pill').forEach((btn) => {
      btn.addEventListener('click', () => switchView(btn.dataset.view));
    });

    dom.btnConnToggle.addEventListener('click', toggleSerialConnection);
    dom.btnSoundToggle.addEventListener('click', () => {
      state.soundEnabled = !state.soundEnabled;
      dom.btnSoundToggle.classList.toggle('active', state.soundEnabled);
      dom.btnSoundToggle.textContent = state.soundEnabled ? '🔊' : '🔇';
      if (state.soundEnabled) playCandyChime(659.25, true);
    });

    const resetModal = document.getElementById('resetConfirmModal');
    const closeResetModal = () => { if (resetModal) resetModal.hidden = true; };
    dom.btnResetDefaults.addEventListener('click', () => {
      if (!isConfigModified()) {
        showToast('当前已是默认设置');
        return;
      }
      if (resetModal) resetModal.hidden = false;
      else resetAllDefaults();
    });
    document.getElementById('btnCloseResetModal')?.addEventListener('click', closeResetModal);
    document.getElementById('btnCancelReset')?.addEventListener('click', closeResetModal);
    document.getElementById('btnConfirmReset')?.addEventListener('click', () => {
      closeResetModal();
      resetAllDefaults();
    });
    resetModal?.addEventListener('click', (e) => {
      if (e.target === resetModal) closeResetModal();
    });

    dom.btnSaveConfig.addEventListener('click', saveAllConfig);

    // 踏板舞台交互（模拟关闭或硬件已连接时，点击仅切换选中踏板，不注入模拟施力）
    for (const pk of PAD_KEYS) {
      const padEl = document.getElementById(`pad-${pk}`);
      if (!padEl) continue;
      padEl.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        if (state.selectedPad !== pk) selectPad(pk);
        if (!state.simTest.enabled || state.serial.connected) return;
        state.pads[pk].mouseDown = true;
        updatePadPointerForce(pk, e.clientX, e.clientY);
      });
      padEl.addEventListener('pointermove', (e) => {
        if (!state.simTest.enabled || state.serial.connected) return;
        if (state.pads[pk].mouseDown) updatePadPointerForce(pk, e.clientX, e.clientY);
      });
      const up = () => clearPadPointerForce(pk);
      padEl.addEventListener('pointerup', up);
      padEl.addEventListener('pointerleave', up);
      padEl.addEventListener('pointercancel', up);
    }

    // 踏板切换（首页与高级页共享联动）
    document.querySelectorAll('[data-select-pad]').forEach((btn) => {
      btn.addEventListener('click', () => selectPad(btn.dataset.selectPad));
    });

    document.querySelectorAll('.preset-chip').forEach((btn) => {
      btn.addEventListener('click', () => applyProfile(btn.dataset.profile));
    });
    dom.btnInnerBoost.addEventListener('click', toggleInnerBoost);

    // 灵敏度模式切换
    dom.btnModeUnified.addEventListener('click', () => {
      state.sensMode = 'unified';
      dom.btnModeUnified.classList.add('active');
      dom.btnModePerEdge.classList.remove('active');
      dom.sensUnifiedBox.classList.add('active');
      dom.sensPerEdgeBox.classList.remove('active');
      syncUnifiedSensitivityUI();
    });

    dom.btnModePerEdge.addEventListener('click', () => {
      state.sensMode = 'per-edge';
      dom.btnModePerEdge.classList.add('active');
      dom.btnModeUnified.classList.remove('active');
      dom.sensPerEdgeBox.classList.add('active');
      dom.sensUnifiedBox.classList.remove('active');
      buildSimpleEdgeList();
    });

    // 灵敏度面板内置「按住试踩」按钮（仅无固件模拟开启时生效）
    if (dom.btnUnifiedTest) {
      dom.btnUnifiedTest.addEventListener('pointerdown', () => {
        if (!state.simTest.enabled) return;
        state.pads[state.selectedPad].panelTestDown = true;
      });
      const releasePanelTest = () => {
        for (const pk of PAD_KEYS) state.pads[pk].panelTestDown = false;
      };
      dom.btnUnifiedTest.addEventListener('pointerup', releasePanelTest);
      dom.btnUnifiedTest.addEventListener('pointerleave', releasePanelTest);
      dom.btnUnifiedTest.addEventListener('pointercancel', releasePanelTest);
    }

    // 整板统一调滑块（拖动按10刻度吸附 + 滴答音）、3位数精确输入框与刻度尺
    dom.sliderUnifiedTrigger.addEventListener('input', (e) => applyUnifiedTriggerValue(e.target.value, { snap: true }));
    bindThreeDigitInput(
      dom.inputUnifiedTrigger,
      (v) => applyUnifiedTriggerValue(v, { snap: false }),
      () => Number(dom.sliderUnifiedTrigger.value)
    );
    mountRuler(dom.unifiedRuler, (v) => applyUnifiedTriggerValue(v, { snap: false }));

    dom.btnGoAdvanced.addEventListener('click', () => switchView('advanced'));

    // 灯光效果
    document.querySelectorAll('.effect-card').forEach((card) => {
      card.addEventListener('click', () => {
        state.lighting.effect = card.dataset.effect;
        syncLightingUI();
        sendSerialCommand(`SET:LED_MODE:${state.lighting.effect.toUpperCase()}`);
      });
    });

    for (const k of PAD_KEYS) {
      document.getElementById(`color-${k}`).addEventListener('input', (e) => {
        state.lighting.colors[k] = e.target.value;
        applyColorsToCss();
      });
    }

    document.querySelectorAll('[data-palette]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const pal = COLOR_PALETTES[btn.dataset.palette];
        if (!pal) return;
        for (const k of PAD_KEYS) state.lighting.colors[k] = pal[k];
        applyColorsToCss();
        showToast(`已切换「${pal.name}」配色`);
      });
    });

    dom.sliderLedBrightness.addEventListener('input', (e) => {
      state.lighting.brightness = Number(e.target.value);
      dom.valLedBrightness.textContent = `${state.lighting.brightness}%`;
    });
    dom.sliderIdleBrightness.addEventListener('input', (e) => {
      state.lighting.idleBrightness = Number(e.target.value);
      dom.valIdleBrightness.textContent = `${state.lighting.idleBrightness}%`;
    });
    dom.sliderLedSpeed.addEventListener('input', (e) => {
      state.lighting.speed = Number(e.target.value);
      dom.valLedSpeed.textContent = `${state.lighting.speed}%`;
    });

    // 按键设置
    document.querySelectorAll('#hidModePills .seg-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.mapping.hidMode = btn.dataset.hid;
        syncMappingUI();
        sendSerialCommand(`SET:HID:${state.mapping.hidMode.toUpperCase()}`);
      });
    });

    document.querySelectorAll('.km-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.km-btn').forEach((b) => b.classList.remove('listening'));
        state.listeningBindFor = btn.dataset.pad;
        btn.classList.add('listening');
        btn.textContent = '请按键...';
      });
    });

    dom.selectPolling.addEventListener('change', (e) => {
      state.mapping.pollingHz = Number(e.target.value);
      sendSerialCommand(`SET:POLL:${state.mapping.pollingHz}`);
    });
    dom.sliderDebounce.addEventListener('input', (e) => {
      state.mapping.debounceMs = Number(e.target.value);
      dom.valDebounce.textContent = `${state.mapping.debounceMs.toFixed(1)} ms`;
    });

    // 高级与校准
    dom.btnCalAll16.addEventListener('click', () => calibrateSensors(null));
    dom.btnCalPad4.addEventListener('click', () => calibrateSensors(state.selectedPad));

    dom.chkAutoDrift.addEventListener('change', (e) => {
      state.baselineCal.autoDriftTrack = e.target.checked;
      sendSerialCommand(`SET:DRIFT_TRACK:${e.target.checked ? 1 : 0}`);
    });
    dom.chkBootAutoCal.addEventListener('change', (e) => {
      state.baselineCal.bootAutoCal = e.target.checked;
      sendSerialCommand(`SET:BOOT_CAL:${e.target.checked ? 1 : 0}`);
    });
    dom.selectPadLogic.addEventListener('change', (e) => {
      state.baselineCal.padLogic = e.target.value;
      sendSerialCommand(`SET:PAD_LOGIC:${e.target.value.toUpperCase()}`);
    });

    dom.selectOscMode.addEventListener('change', (e) => {
      state.oscMode = e.target.value;
      updateOscSubtitle();
    });

    dom.btnToggleWave.addEventListener('click', () => {
      state.wavePaused = !state.wavePaused;
      dom.btnToggleWave.textContent = state.wavePaused ? '继续' : '暂停';
    });

    dom.btnSendSerialCmd.addEventListener('click', () => {
      const cmd = dom.serialCmdInput.value.trim();
      if (!cmd) return;
      sendSerialCommand(cmd);
      dom.serialCmdInput.value = '';
    });
    dom.serialCmdInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') dom.btnSendSerialCmd.click();
    });
    dom.btnBootsel.addEventListener('click', () => {
      sendSerialCommand('CMD:BOOTSEL');
      showToast('已发送进入刷机模式指令');
    });

    // JSON 弹窗
    document.getElementById('btnOpenJsonModal').addEventListener('click', () => {
      dom.jsonConfigArea.value = JSON.stringify(exportConfigObject(), null, 2);
      dom.exportModal.hidden = false;
    });
    document.getElementById('btnCloseExportModal').addEventListener('click', () => { dom.exportModal.hidden = true; });
    dom.exportModal.addEventListener('click', (e) => { if (e.target === dom.exportModal) dom.exportModal.hidden = true; });

    document.getElementById('btnCopyJson').addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(dom.jsonConfigArea.value);
        showToast('已复制到剪贴板');
      } catch (_) {
        dom.jsonConfigArea.select();
        document.execCommand('copy');
        showToast('已复制配置');
      }
    });

    document.getElementById('btnDownloadJson').addEventListener('click', () => {
      const blob = new Blob([dom.jsonConfigArea.value], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'sugarstep_config.json';
      a.click();
      URL.revokeObjectURL(url);
    });

    document.getElementById('btnApplyJson').addEventListener('click', () => {
      try {
        importConfigObject(JSON.parse(dom.jsonConfigArea.value));
        dom.exportModal.hidden = true;
        showToast('配置已应用');
      } catch (err) {
        showToast(`格式有误: ${err.message}`);
      }
    });

    // [SIM-TEST] 无固件模拟测试卡片交互（若 HTML 中已移除 #devSimCard 则自动跳过，零报错）
    const chkSimMode = document.getElementById('chkSimMode');
    const sliderSimHold = document.getElementById('sliderSimHold');
    const inputSimHold = document.getElementById('inputSimHold');
    const simRuler = document.getElementById('simRuler');
    const btnSimSinglePulse = document.getElementById('btnSimSinglePulse');
    const btnSimClearForce = document.getElementById('btnSimClearForce');

    const applySimHoldForce = (rawVal, { snap = false } = {}) => {
      if (!state.simTest.enabled) return;
      const prevVal = state.pads[state.selectedPad].simHoldForce || 0;
      const val = snap ? snapSimStep(rawVal) : Math.max(0, Math.min(SCALE_MAX, Math.round(Number(rawVal) || 0)));
      if (snap && val !== prevVal) playRulerTick();
      state.pads[state.selectedPad].simHoldForce = val;
      if (sliderSimHold) sliderSimHold.value = String(val);
      if (inputSimHold) inputSimHold.value = String(val);
      highlightRulerTick(simRuler, val);
    };

    if (chkSimMode) {
      chkSimMode.addEventListener('change', (e) => {
        setSimTestEnabled(e.target.checked);
        showToast(e.target.checked ? '已开启无固件模拟测试' : '已关闭模拟测试（纯净硬件界面）');
      });
    }

    if (sliderSimHold) {
      sliderSimHold.addEventListener('input', (e) => applySimHoldForce(e.target.value, { snap: true }));
    }
    bindThreeDigitInput(
      inputSimHold,
      (v) => applySimHoldForce(v, { snap: false }),
      () => state.pads[state.selectedPad].simHoldForce || 0
    );
    mountRuler(simRuler, (v) => applySimHoldForce(v, { snap: false }));
    highlightRulerTick(simRuler, state.pads[state.selectedPad].simHoldForce || 0);

    if (btnSimSinglePulse) {
      btnSimSinglePulse.addEventListener('click', () => {
        if (!state.simTest.enabled) return;
        const targetPadKey = state.selectedPad;
        const pad = state.pads[targetPadKey];
        pad.panelTestDown = true;
        clearTimeout(pad._pulseTimer);
        pad._pulseTimer = setTimeout(() => {
          pad.panelTestDown = false;
        }, 220);
      });
    }

    if (btnSimClearForce) {
      btnSimClearForce.addEventListener('click', () => {
        clearAllSimForces();
        showToast('已清空模拟施力');
      });
    }

    // 键盘监听
    window.addEventListener('keydown', (e) => {
      if (state.listeningBindFor) {
        e.preventDefault();
        const target = state.listeningBindFor;
        const newKey = e.key === ' ' ? 'Space' : e.key;
        state.mapping.keys[target] = newKey;
        state.listeningBindFor = null;
        document.querySelectorAll('.km-btn').forEach((b) => b.classList.remove('listening'));
        syncMappingUI();
        return;
      }

      if (e.key === 'Escape') {
        if (resetModal && !resetModal.hidden) { closeResetModal(); return; }
        if (dom.exportModal && !dom.exportModal.hidden) { dom.exportModal.hidden = true; return; }
      }

      if (!state.simTest.enabled || state.serial.connected) return;
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT')) return;

      const keyNorm = e.key === ' ' ? 'Space' : e.key;
      const lower = e.key.toLowerCase();
      let matchedPad = null;
      if (keyNorm === state.mapping.keys.left || lower === 'd') matchedPad = 'left';
      else if (keyNorm === state.mapping.keys.down || lower === 'f') matchedPad = 'down';
      else if (keyNorm === state.mapping.keys.up || lower === 'j') matchedPad = 'up';
      else if (keyNorm === state.mapping.keys.right || lower === 'k') matchedPad = 'right';

      if (matchedPad) {
        if (['ArrowLeft', 'ArrowDown', 'ArrowUp', 'ArrowRight'].includes(e.key)) e.preventDefault();
        state.pads[matchedPad].keyDown = true;
      } else if (keyNorm === state.mapping.keys.start) {
        playCandyChime(880, true);
      } else if (keyNorm === state.mapping.keys.select) {
        playCandyChime(440, true);
      }
    });

    window.addEventListener('keyup', (e) => {
      const keyNorm = e.key === ' ' ? 'Space' : e.key;
      const lower = e.key.toLowerCase();
      if (keyNorm === state.mapping.keys.left || lower === 'd') state.pads.left.keyDown = false;
      if (keyNorm === state.mapping.keys.down || lower === 'f') state.pads.down.keyDown = false;
      if (keyNorm === state.mapping.keys.up || lower === 'j') state.pads.up.keyDown = false;
      if (keyNorm === state.mapping.keys.right || lower === 'k') state.pads.right.keyDown = false;
    });

    window.addEventListener('blur', clearAllSimForces);
  }

  // =========================================================================
  // 12. 启动
  // =========================================================================
  function init() {
    initLedStripBeads();
    loadSavedConfig();
    bindEvents();
    const chkSimMode = document.getElementById('chkSimMode');
    setSimTestEnabled(Boolean(chkSimMode && chkSimMode.checked));
    selectPad('left');
    syncLightingUI();
    syncMappingUI();
    appendSerialLog('SugarStep 就绪 (16 路独立压感)', 'sys');
    requestAnimationFrame(mainLoop);
  }

  init();
})();
