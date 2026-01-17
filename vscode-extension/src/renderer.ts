import type { ActivationFunction } from 'vscode-notebook-renderer';

export const activate: ActivationFunction = (context) => {
  return {
    renderOutputItem(data, element) {
      const asset = data.json();
      
      if (!asset || !asset.path) {
        element.innerText = '⚠️ Invalid Asset Data';
        return;
      }

      // Logic: If path is relative, resolve it. 
      // Note: In a real renderer, we need to convert the file path to a VS Code Webview URI.
      // Since renderers run in a sandbox, we pass the path to an img tag.
      // Ideally, the server sends the base64 data here for immediate rendering, 
      // OR we use a special URI scheme handled by the extension.
      
      // Simpler V1 approach: Server sends 'path', we render a "Click to View" 
      // or try to load it if the sandbox allows.
      
      const container = document.createElement('div');
      container.style.padding = '10px';
      container.style.border = '1px solid #ccc';
      
      const img = document.createElement('img');
      // Note: This requires the extension to enable local resource loading
      img.src = asset.path; 
      img.style.maxWidth = '100%';
      img.alt = asset.alt || 'Asset';
      
      const label = document.createElement('div');
      label.innerText = `📦 Asset: ${asset.path} (${asset.type})`;
      label.style.fontSize = '0.8em';
      label.style.color = '#888';

      container.appendChild(img);
      container.appendChild(label);
      element.appendChild(container);
    }
  };
};
