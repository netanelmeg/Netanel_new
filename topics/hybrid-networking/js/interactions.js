function initInteractions(svg) {
  const panel = document.getElementById('panel');
  const controls = document.getElementById('controls');
  let currentScenario = 'explore';
  let isQuizActive = false;

  function renderNodeDetails(nodeId) {
    const data = NODE_DATA[nodeId];
    if (!data) return;
    let html = '';
    if (data.tag) html += `<span class="tag">${data.tag}</span>`;
    html += `<h2>${data.title}</h2>`;
    html += `<p>${data.description}</p>`;
    if (data.bullets) {
      html += '<ul>';
      data.bullets.forEach(b => { html += `<li>${b}</li>`; });
      html += '</ul>';
    }
    if (data.gotcha) html += `<div class="gotcha">⚠️ <strong>Gotcha:</strong> ${data.gotcha}</div>`;
    if (data.tip)    html += `<div class="tip">💡 <strong>Tip:</strong> ${data.tip}</div>`;
    panel.innerHTML = html;
  }

  function renderScenario(scenarioId) {
    const s = SCENARIOS[scenarioId];
    if (!s) return;
    clearAllStates(svg);

    if (scenarioId === 'explore') {
      panel.innerHTML = `
        <span class="tag">EXPLORE MODE</span>
        <h2>${s.title}</h2>
        <p>${s.description}</p>
        <p><strong>Try this:</strong></p>
        <ul>
          <li>Tap <strong>Spoke-A</strong> or <strong>Spoke-B</strong> to see how spokes work</li>
          <li>Tap <strong>Azure Firewall</strong> to learn what holds hub-and-spoke together</li>
          <li>Tap <strong>BGP</strong> or <strong>LNG</strong> to revisit dynamic routing</li>
        </ul>`;
      return;
    }

    dimAll(svg);
    highlightNodes(svg, s.activeNodes);
    animateArrows(svg, s.activeArrows);

    let html = `<span class="tag">${s.tag}</span>`;
    html += `<h2>${s.title}</h2>`;
    html += `<p>${s.description}</p>`;
    if (s.steps) {
      html += '<ol>';
      s.steps.forEach(step => { html += `<li>${step}</li>`; });
      html += '</ol>';
    }
    if (s.gotcha) html += `<div class="gotcha">⚠️ <strong>Gotcha:</strong> ${s.gotcha}</div>`;
    if (s.tip)    html += `<div class="tip">💡 <strong>Tip:</strong> ${s.tip}</div>`;
    panel.innerHTML = html;
  }

  // Scenario button clicks — only buttons with data-scenario, so the quiz button is unaffected
  controls.querySelectorAll('[data-scenario]').forEach(btn => {
    btn.addEventListener('click', () => {
      controls.querySelectorAll('[data-scenario]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentScenario = btn.dataset.scenario;
      renderScenario(currentScenario);
    });
  });

  // Node clicks — blocked while quiz is active
  svg.querySelectorAll('.clickable').forEach(node => {
    node.addEventListener('click', e => {
      e.stopPropagation();
      if (isQuizActive) return;
      const nodeId = node.dataset.node;
      if (!nodeId) return;

      if (currentScenario !== 'explore') {
        controls.querySelectorAll('[data-scenario]').forEach(b => b.classList.remove('active'));
        controls.querySelector('[data-scenario="explore"]').classList.add('active');
        currentScenario = 'explore';
        clearAllStates(svg);
      }

      selectNode(svg, nodeId);
      renderNodeDetails(nodeId);
    });
  });

  renderScenario('explore');

  return {
    setQuizActive(flag) {
      isQuizActive = flag;
      controls.classList.toggle('quiz-active', flag);
    },
    renderScenario,
  };
}
