const canvas = document.getElementById('meshCanvas') || document.querySelector('canvas');
const ctx = canvas ? canvas.getContext('2d') : null;

let nodes = [];
let links = [];

if (canvas) {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  window.addEventListener('resize', () => {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  });
}

async function fetchTopology() {
  try {
    const res = await fetch('/topology.json?t=' + Date.now());
    if (!res.ok) return;
    const data = await res.json();
    
    // Sync node coordinates while preserving existing layout positions
    const existingMap = new Map(nodes.map(n => [n.id, n]));
    
    nodes = data.nodes.map((n, idx) => {
      if (existingMap.has(n.id)) {
        const old = existingMap.get(n.id);
        return { ...n, x: old.x, y: old.y, vx: old.vx, vy: old.vy };
      }
      // Position new nodes in a circular layout
      const angle = (idx / data.nodes.length) * Math.PI * 2;
      const radius = 180;
      const cx = (canvas ? canvas.width : 800) / 2;
      const cy = (canvas ? canvas.height : 600) / 2;
      return {
        ...n,
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        vx: 0,
        vy: 0
      };
    });

    links = data.links;
  } catch (err) {
    console.warn("Topology fetch pending...", err);
  }
}

function stepPhysics() {
  if (!canvas || !ctx) return;
  
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;

  // Draw Links
  ctx.strokeStyle = "rgba(0, 255, 128, 0.4)";
  ctx.lineWidth = 1.5;
  links.forEach(link => {
    const sourceNode = nodes.find(n => n.id === link.source);
    const targetNode = nodes.find(n => n.id === link.target);
    if (sourceNode && targetNode) {
      ctx.beginPath();
      ctx.moveTo(sourceNode.x, sourceNode.y);
      ctx.lineTo(targetNode.x, targetNode.y);
      ctx.stroke();
    }
  });

  // Draw & Orbit Nodes
  nodes.forEach(node => {
    // Gentle spring pull toward center
    node.vx += (cx - node.x) * 0.001;
    node.vy += (cy - node.y) * 0.001;
    node.x += node.vx;
    node.y += node.vy;
    node.vx *= 0.92;
    node.vy *= 0.92;

    // Node Outer Glow
    ctx.beginPath();
    ctx.arc(node.x, node.y, 12, 0, Math.PI * 2);
    ctx.fillStyle = node.status === 'active' ? 'rgba(0, 255, 128, 0.25)' : 'rgba(255, 64, 64, 0.25)';
    ctx.fill();

    // Node Core
    ctx.beginPath();
    ctx.arc(node.x, node.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = node.status === 'active' ? '#00ff80' : '#ff4040';
    ctx.fill();

    // Text Label
    ctx.fillStyle = '#e0e0e0';
    ctx.font = '12px monospace';
    ctx.fillText(node.label || node.id, node.x + 12, node.y + 4);
  });

  requestAnimationFrame(stepPhysics);
}

// Initialization
setInterval(fetchTopology, 3000);
fetchTopology();
if (canvas) requestAnimationFrame(stepPhysics);
