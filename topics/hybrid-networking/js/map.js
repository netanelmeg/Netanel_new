async function loadMap(containerId, svgPath) {
  const container = document.getElementById(containerId);
  const res = await fetch(svgPath);
  if (!res.ok) throw new Error(`Failed to load map: HTTP ${res.status}`);
  const text = await res.text();
  container.innerHTML = text;
  return container.querySelector('svg');
}

function clearAllStates(svg) {
  svg.querySelectorAll('.clickable').forEach(n => {
    n.classList.remove('dimmed', 'highlighted', 'selected');
  });
  svg.querySelectorAll('.arrow-line').forEach(a => {
    a.classList.remove('dimmed', 'flowing');
  });
  svg.querySelectorAll('.arrow-label').forEach(a => {
    a.classList.remove('dimmed', 'highlighted');
  });
}

function dimAll(svg) {
  svg.querySelectorAll('.clickable').forEach(n => n.classList.add('dimmed'));
  svg.querySelectorAll('.arrow-line').forEach(a => a.classList.add('dimmed'));
  svg.querySelectorAll('.arrow-label').forEach(a => a.classList.add('dimmed'));
}

function highlightNodes(svg, nodeIds) {
  nodeIds.forEach(id => {
    const node = svg.querySelector(`[data-node="${id}"]`);
    if (node) {
      node.classList.remove('dimmed');
      node.classList.add('highlighted');
    }
  });
}

function animateArrows(svg, arrowIds) {
  arrowIds.forEach(id => {
    const line = svg.querySelector(`[data-arrow="${id}"]`);
    if (line) {
      line.classList.remove('dimmed');
      line.classList.add('flowing');
    }
    svg.querySelectorAll(`[data-label="${id}"]`).forEach(lbl => {
      lbl.classList.remove('dimmed');
      lbl.classList.add('highlighted');
    });
  });
}

function selectNode(svg, nodeId) {
  svg.querySelectorAll('.clickable').forEach(n => n.classList.remove('selected'));
  const node = svg.querySelector(`[data-node="${nodeId}"]`);
  if (node) node.classList.add('selected');
}
