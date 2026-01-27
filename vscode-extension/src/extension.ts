import * as vscode from 'vscode';
import { McpClient } from './mcpClient';
import { MCPKernel } from './mcpKernel';
import { SetupManager } from './setupManager';
import { QuickStartWizard } from './quickStartWizard';
import { DatabaseService } from './database';
import { SnapshotTreeDataProvider } from './snapshotTreeDataProvider';
import { SnapshotViewer } from './snapshotViewer';

let quickStartWizard: QuickStartWizard;
let dbService: DatabaseService;

export async function activate(context: vscode.ExtensionContext) {
    console.log('Congratulations, your extension "mcp-jupyter" is now active!');

    // Initialize the database service
    dbService = new DatabaseService(context);
    await dbService.init();

    // Initialize the core components
    const setupManager = new SetupManager(context);
    const mcpClient = McpClient.getInstance('ws://localhost:8888', 'test-session', new MCPKernel());
    quickStartWizard = new QuickStartWizard(context, setupManager, mcpClient);

    // Register the snapshot components
    const snapshotTreeDataProvider = new SnapshotTreeDataProvider(dbService);
    const snapshotViewer = new SnapshotViewer(dbService);

    vscode.window.registerTreeDataProvider('mcp-jupyter-snapshots', snapshotTreeDataProvider);

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('mcp-jupyter.quickStart', () => quickStartWizard.show()),
        vscode.commands.registerCommand('mcp-jupyter.viewSnapshot', (snapshot) => snapshotViewer.viewSnapshot(snapshot)),
        vscode.commands.registerCommand('mcp-jupyter.saveSnapshot', async () => {
            const snapshotName = await vscode.window.showInputBox({ prompt: 'Enter a name for the snapshot' });
            if (snapshotName) {
                // In a real implementation, we would get the variables from the MCPKernel
                const dummyVariables = [
                    { name: 'df', type: 'DataFrame', preview: '[100 rows x 5 cols]', timestamp: Math.floor(Date.now() / 1000) },
                    { name: 'x', type: 'int', preview: '42', timestamp: Math.floor(Date.now() / 1000) }
                ];
                const activeNotebook = vscode.window.activeNotebookEditor?.notebook.uri.fsPath ?? 'unknown';
                await dbService.saveSnapshot(snapshotName, activeNotebook, dummyVariables);
                snapshotTreeDataProvider.refresh();
            }
        }),
        vscode.commands.registerCommand('mcp-jupyter.clearSnapshots', async () => {
            await dbService.clearAllSnapshots();
            snapshotTreeDataProvider.refresh();
        })
    );

    // Automatically show the wizard if setup has not been completed
    quickStartWizard.showIfNeeded();

    // Register the kernel
    context.subscriptions.push(
        vscode.notebook.registerNotebookKernelProvider(
            { viewType: 'mcp-jupyter-notebook' },
            {
                provideKernels: async () => {
                    const isSetupComplete = context.globalState.get('mcp.hasCompletedSetup', false);
                    if (isSetupComplete) {
                        return [new MCPKernel()];
                    }
                    return [];
                }
            }
        )
    );
}

export function deactivate() {
    if (quickStartWizard) {
        quickStartWizard.dispose();
    }
    if (dbService) {
        dbService.close();
    }
}
