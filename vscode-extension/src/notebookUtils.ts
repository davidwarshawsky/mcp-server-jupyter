import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

/**
 * Creates and opens a sample notebook to demonstrate MCP Jupyter's features.
 * @param context The extension context.
 */
export async function openTestNotebook(context: vscode.ExtensionContext): Promise<void> {
    const examplePath = path.join(context.extensionPath, 'examples', 'quickstart.ipynb');
    const examplesDir = path.dirname(examplePath);

    if (!fs.existsSync(examplesDir)) {
        fs.mkdirSync(examplesDir, { recursive: true });
    }

    // Define the content of the example notebook
    const exampleNotebook = {
        cells: [
            {
                cell_type: 'markdown',
                source: [
                    '# Welcome to MCP Jupyter!\n',
                    'This notebook is a quick tour of the key features.\n',
                    '## Step 1: Select the MCP Kernel\n',
                    'If you haven\'t already, click the kernel picker in the top-right and select **MCP Kernel**.'
                ]
            },
            {
                cell_type: 'code',
                source: [
                    '# Test basic execution\n',
                    'import sys\n',
                    'print("Hello from MCP Jupyter!")\n',
                    'print(f"Using Python {sys.version}")'
                ]
            },
            {
                cell_type: 'markdown',
                source: ['## Step 2: Explore Your Data\n', 'Create a DataFrame and see how MCP Jupyter helps you explore it.']
            },
            {
                cell_type: 'code',
                source: [
                    'import pandas as pd\n',
                    'data = pd.DataFrame({\n',
                    '    "city": ["New York", "London", "Tokyo", "Paris", "Sydney"],\n',
                    '    "temperature": [15, 12, 20, 18, 25],\n',
                    '    "humidity": [65, 75, 60, 80, 70]\n',
                    '})\n',
                    'print("DataFrame created. Check the MCP Variables panel in the sidebar!")'
                ]
            }
        ],
        metadata: {
            kernelspec: {
                display_name: 'Python 3',
                language: 'python',
                name: 'python3'
            }
        },
        nbformat: 4,
        nbformat_minor: 2
    };

    fs.writeFileSync(examplePath, JSON.stringify(exampleNotebook, null, 2));

    const doc = await vscode.workspace.openNotebookDocument(vscode.Uri.file(examplePath));
    await vscode.window.showNotebookDocument(doc);
}
