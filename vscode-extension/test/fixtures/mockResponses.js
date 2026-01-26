"use strict";
/**
 * Mock responses from MCP server for testing
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.mockResponses = void 0;
exports.mockResponses = {
    listEnvironments: {
        jsonrpc: '2.0',
        id: 1,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify([
                        {
                            name: 'base',
                            type: 'conda',
                            path: '/opt/conda/envs/base/bin/python',
                            python_version: '3.10.0',
                        },
                        {
                            name: 'test-env',
                            type: 'venv',
                            path: '/home/user/.venv/test-env/bin/python',
                            python_version: '3.11.0',
                        },
                    ]),
                },
            ],
        },
    },
    startKernel: {
        jsonrpc: '2.0',
        id: 2,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        status: 'started',
                        kernel_id: 'test-kernel-id',
                    }),
                },
            ],
        },
    },
    runCellAsync: {
        jsonrpc: '2.0',
        id: 3,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        task_id: 'test-task-id-001',
                        status: 'queued',
                    }),
                },
            ],
        },
    },
    getExecutionStream: {
        jsonrpc: '2.0',
        id: 4,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        task_id: 'test-task-id-001',
                        status: 'completed',
                        outputs: [
                            {
                                output_type: 'stream',
                                name: 'stdout',
                                text: 'Hello from test notebook\n',
                            },
                        ],
                        execution_count: 1,
                    }),
                },
            ],
        },
    },
    getExecutionStreamError: {
        jsonrpc: '2.0',
        id: 5,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        task_id: 'test-task-id-002',
                        status: 'error',
                        outputs: [
                            {
                                output_type: 'error',
                                ename: 'ValueError',
                                evalue: 'This is a test error',
                                traceback: [
                                    'Traceback (most recent call last):',
                                    '  File "<stdin>", line 1, in <module>',
                                    'ValueError: This is a test error',
                                ],
                            },
                        ],
                        execution_count: 2,
                    }),
                },
            ],
        },
    },
    stopKernel: {
        jsonrpc: '2.0',
        id: 6,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        status: 'stopped',
                    }),
                },
            ],
        },
    },
    detectSyncNeeded: {
        jsonrpc: '2.0',
        id: 7,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        sync_needed: false,
                        reason: 'Notebook not modified',
                    }),
                },
            ],
        },
    },
    cancelExecution: {
        jsonrpc: '2.0',
        id: 8,
        result: {
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        status: 'cancelled',
                        task_id: 'test-task-id-001',
                    }),
                },
            ],
        },
    },
};
exports.default = exports.mockResponses;
//# sourceMappingURL=mockResponses.js.map