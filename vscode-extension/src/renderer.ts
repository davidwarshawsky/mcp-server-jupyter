/**
 * MCP Asset Renderer
 * 
 * Renders assets (images, plots) inline in notebook outputs.
 * 
 * Supports two modes:
 * 1. Base64 embedded: { type: "image/png", content: "base64...", alt: "..." }
 * 2. File path: { path: "assets/plot_123.png", type: "image/png" }
 * 
 * The renderer automatically detects which mode based on presence of 'content'.
 */
import type { ActivationFunction, OutputItem, RendererContext } from 'vscode-notebook-renderer';

interface McpAsset {
  path?: string;           // File path (relative to workspace)
  type: string;            // MIME type (image/png, image/svg+xml, etc.)
  content?: string;        // Base64-encoded content (optional)
  alt?: string;            // Alt text for accessibility
}

/**
 * Renders an image from either base64 content or file path
 */
function renderImage(asset: McpAsset, container: HTMLDivElement, context: RendererContext<void>): void {
  const img = document.createElement('img');
  
  if (asset.content) {
    // Mode 1: Base64 embedded content
    img.src = `data:${asset.type};base64,${asset.content}`;
  } else if (asset.path) {
    // Mode 2: File path - use VS Code's webview resource URI
    // In notebook renderers, we can use the workspace file protocol
    // The renderer runs in a sandboxed iframe, so we need to handle this carefully
    
    // Try to construct a file:// URL for local assets
    // Note: This requires the asset folder to be in the workspace
    const isAbsolute = asset.path.startsWith('/') || /^[A-Za-z]:[\\/]/.test(asset.path);
    if (isAbsolute) {
      // Absolute path - use file:// protocol (may be blocked by CSP)
      img.src = `file://${asset.path}`;
    } else {
      // Relative path - assume it's relative to notebook
      // Use the vscode-resource scheme for notebook webviews
      img.src = asset.path;
    }
    
    // Add error handler for path-based loading
    img.onerror = () => {
      // Fallback: Show the path as a clickable link
      container.innerHTML = '';
      const fallback = document.createElement('div');
      fallback.style.cssText = 'padding: 10px; background: #f0f0f0; border-radius: 4px; font-family: monospace;';
      fallback.innerHTML = `
        <span style="color: #666;">📁 Asset saved to:</span><br>
        <code style="color: #0066cc; cursor: pointer;" title="Click to copy path">${asset.path}</code>
        <br><small style="color: #888;">Image cannot be displayed inline. Click path to copy.</small>
      `;
      fallback.querySelector('code')?.addEventListener('click', () => {
        navigator.clipboard.writeText(asset.path || '');
        fallback.querySelector('small')!.textContent = '✓ Path copied!';
      });
      container.appendChild(fallback);
    };
  } else {
    container.innerText = '⚠️ Invalid Asset: No content or path provided.';
    return;
  }
  
  img.style.maxWidth = '100%';
  img.style.borderRadius = '4px';
  img.alt = asset.alt || 'MCP Asset';
  
  container.appendChild(img);
}

/**
 * Renders a label below the asset
 */
function renderLabel(asset: McpAsset, container: HTMLDivElement): void {
  const label = document.createElement('div');
  label.style.cssText = 'font-size: 0.75em; color: #888; margin-top: 4px;';
  
  const icon = asset.type.startsWith('image/svg') ? '🎨' : '📊';
  const source = asset.content ? 'embedded' : (asset.path || 'unknown');
  label.innerText = `${icon} ${asset.alt || asset.type} ${asset.content ? '' : `• ${source}`}`;
  
  container.appendChild(label);
}

export const activate: ActivationFunction = (_context: RendererContext<void>) => {
  return {
    renderOutputItem(data: OutputItem, element: HTMLElement): void {
      let asset: McpAsset;
      
      try {
        asset = data.json() as McpAsset;
      } catch {
        element.innerText = '⚠️ Invalid Asset Data: Could not parse JSON.';
        return;
      }
      
      if (!asset || !asset.type) {
        element.innerText = '⚠️ Invalid Asset Data: Missing type field.';
        return;
      }
      
      // Need either content (base64) or path
      if (!asset.content && !asset.path) {
        element.innerText = '⚠️ Invalid Asset Data: Missing both content and path.';
        return;
      }

      const container = document.createElement('div');
      container.style.cssText = 'padding: 8px; display: inline-block;';
      
      // Render based on asset type
      if (asset.type.startsWith('image/')) {
        renderImage(asset, container, _context);
      } else if (asset.type === 'text/plain' && asset.path) {
        // Text asset - show as downloadable link
        const link = document.createElement('a');
        link.href = asset.path;
        link.download = asset.path.split('/').pop() || 'output.txt';
        link.style.cssText = 'color: #0066cc; text-decoration: underline;';
        link.innerHTML = `📄 ${asset.alt || 'Text Output'} <small>(${asset.path})</small>`;
        container.appendChild(link);
      } else {
        // Unknown type - show info
        container.innerHTML = `<code>Asset: ${asset.type}</code>`;
      }
      
      // Add label for context
      renderLabel(asset, container);
      
      element.appendChild(container);
    }
  };
};
