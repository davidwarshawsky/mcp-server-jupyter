import type { ActivationFunction } from 'vscode-notebook-renderer';

export const activate: ActivationFunction = (context) => {
  return {
    renderOutputItem(data, element) {
      const asset = data.json();
      
      if (!asset || !asset.content || !asset.type) {
        element.innerText = '⚠️ Invalid Asset Data: Missing content or type.';
        return;
      }

      // Create a data URI from the base64 content and MIME type
      const dataUri = `data:${asset.type};base64,${asset.content}`;
      
      const container = document.createElement('div');
      container.style.padding = '10px';
      
      const img = document.createElement('img');
      img.src = dataUri; 
      img.style.maxWidth = '100%';
      img.alt = asset.alt || 'Embedded Asset';
      
      // Optional: Display a small label for context
      const label = document.createElement('div');
      label.innerText = `📦 Embedded Asset: ${asset.alt || asset.type}`;
      label.style.fontSize = '0.8em';
      label.style.color = '#888';
      label.style.marginTop = '5px';

      container.appendChild(img);
      container.appendChild(label);
      element.appendChild(container);
    }
  };
};
