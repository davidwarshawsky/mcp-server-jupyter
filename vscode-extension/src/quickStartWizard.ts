import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { exec } from 'child_process';
import { SetupManager } from './setupManager';
import { McpClient } from './mcpClient';
import { SetupWebview } from './SetupWebview';

export class QuickStartWizard {
    // ... (properties are the same)

    constructor(
        private context: vscode.ExtensionContext,
        private setupManager: SetupManager,
        private mcpClient: McpClient
    ) {
        this.setupWebview = new SetupWebview(context, this.runSetup.bind(this));
        // ... (statusBarItem setup is the same)

        // Register the validation command
        context.subscriptions.push(vscode.commands.registerCommand(
            'mcp-jupyter.validatePythonPath', 
            this.validatePythonPath.bind(this)
        ));
    }

    private async validatePythonPath(pythonPath: string): Promise<boolean> {
        if (!pythonPath || !fs.existsSync(pythonPath)) {
            return false;
        }

        // 1. Check if it's a file and executable.
        try {
            fs.accessSync(pythonPath, fs.constants.X_OK);
        } catch (err) {
            return false; // Not executable
        }

        // 2. Check for `pip` and `venv` modules, which are essential.
        const command = `"${pythonPath}" -c "import pip; import venv"`;
        return new Promise<boolean>(resolve => {
            exec(command, (error) => {
                resolve(!error);
            });
        });
    }
    
    // ... (rest of the quickStartWizard.ts file)
}
