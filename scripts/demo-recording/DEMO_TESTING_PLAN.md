# Demo Recording Testing Plan

> **Purpose:** Track progress on demo recordings for advertising materials and tutorials for mcp-server-jupyter.  
> **Last Updated:** 2026-01-21  
> **Status:** 🔴 IN PROGRESS

---

## Executive Summary

This document tracks the creation of demo videos that showcase the key features of `mcp-server-jupyter`. These demos will be used for:
- README.md hero GIFs
- Documentation tutorials
- Marketing/advertising materials
- Feature showcase pages

---

## Environment Setup

### Docker-Based Recording Environment
- **Container:** `demo-code-server` (linuxserver/code-server)
- **Port:** 8443
- **Workspace:** `/config/workspace` (mounted from project root)
- **Extensions Required:**
  - [x] ms-toolsai.jupyter
  - [x] ms-python.python
  - [x] jupyter-renderers
- **Python Packages:**
  - [x] ipykernel
  - [x] pandas
  - [ ] duckdb (for SQL magic demos)
  - [ ] matplotlib (for visualization demos)

### Playwright Configuration
- **Config:** `scripts/demo-recording/playwright.demo.config.ts`
- **Output:** `scripts/demo-recording/demo-recordings/`
- **Video Format:** WebM (converted to GIF for docs)

---

## Demo 1: DuckDB SQL Magic

### Objective
Show how to use the `%%duckdb` magic command to run SQL queries directly on pandas DataFrames.

### Status: � IN PROGRESS (v4 - Needs video review)

### Test File
`scripts/demo-recording/demo-tests/duckdb-magic.spec.ts`

### Expected Workflow
| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Navigate to code-server | VS Code workbench loads | ✅ |
| 2 | Wait for activity bar | Activity bar visible | ✅ |
| 3 | Wait for extensions | Extensions initialized | ✅ |
| 4 | Open demo.ipynb via Ctrl+P | Quick Open shows demo.ipynb | ✅ |
| 5 | Press Enter to open file | Notebook opens in editor | ✅ |
| 6 | Wait for notebook to render | Notebook cells visible with proper syntax highlighting | 🔴 FAILING |
| 7 | Select Python kernel | Kernel selected and shows "idle" | ⬜ NOT TESTED |
| 8 | Click on first CODE cell (not markdown) | Cell is focused with cursor | 🔴 FAILING |
| 9 | Run first cell (Shift+Enter) | DataFrame output displayed | ⬜ NOT TESTED |
| 10 | Click on second CODE cell | SQL cell is focused | ⬜ NOT TESTED |
| 11 | Run second cell (Shift+Enter) | SQL query results displayed | ⬜ NOT TESTED |
| 12 | Show final results | Both outputs visible | ⬜ NOT TESTED |

### Current Issues
1. **Clicking on Markdown cell instead of Code cell** - Script is selecting the wrong cell type
2. **Pressing newline instead of running cell** - Wrong keyboard command being sent
3. **Kernel not being selected** - Need to explicitly select Python 3 kernel

### Demo Notebook Content (`demo.ipynb`)
```
Cell 1 (Markdown): # DuckDB SQL Magic Demo
Cell 2 (Code): 
    import pandas as pd
    sales = pd.DataFrame({
        "region": ["North", "South", "East", "West"],
        "revenue": [10000, 15000, 12000, 18000]
    })
    sales

Cell 3 (Code):
    %%duckdb
    SELECT * FROM sales
    WHERE revenue > 12000
    ORDER BY revenue DESC
```

### Required Fixes
- [ ] Skip markdown cells - only click on code cells
- [ ] Use Shift+Enter to run cells (not just Enter)
- [ ] Properly select kernel if prompted
- [ ] Wait for cell execution to complete before moving to next cell
- [ ] Verify output is displayed before proceeding

---

## Demo 2: Quick Start Tutorial

### Objective
Show a new user how to get started with mcp-server-jupyter in under 60 seconds.

### Status: ⬜ NOT STARTED

### Expected Workflow
| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Open VS Code with Jupyter extension | Extension loaded | ⬜ |
| 2 | Open a .ipynb file | Notebook renders | ⬜ |
| 3 | Connect to MCP server | Connection established | ⬜ |
| 4 | Run a simple cell | Output displayed | ⬜ |
| 5 | Show MCP integration | AI can read/write cells | ⬜ |

---

## Demo 3: Asset Rendering

### Objective
Show how mcp-server-jupyter handles rich output like images, charts, and DataFrames.

### Status: ⬜ NOT STARTED

### Expected Workflow
| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Open asset-demo.ipynb | Notebook opens | ⬜ |
| 2 | Run matplotlib cell | Chart renders inline | ⬜ |
| 3 | Run DataFrame cell | Styled table output | ⬜ |
| 4 | Run image cell | Image displays | ⬜ |
| 5 | Show wide DataFrame | Horizontal scroll works | ⬜ |

---

## Demo 4: Cell Manipulation

### Objective
Show how to add, delete, move, and edit cells programmatically.

### Status: ⬜ NOT STARTED

### Expected Workflow
| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Open empty notebook | Blank notebook | ⬜ |
| 2 | Add code cell | Cell appears | ⬜ |
| 3 | Type code | Code appears in cell | ⬜ |
| 4 | Run cell | Output shows | ⬜ |
| 5 | Add markdown cell | Markdown cell added | ⬜ |
| 6 | Move cells | Cell order changes | ⬜ |
| 7 | Delete cell | Cell removed | ⬜ |

---

## Demo 5: Emergency Stop

### Objective
Show the emergency stop feature that kills runaway kernels.

### Status: ⬜ NOT STARTED

### Expected Workflow
| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Run infinite loop cell | Cell shows running | ⬜ |
| 2 | Trigger emergency stop | Kernel interrupted | ⬜ |
| 3 | Show kernel recovered | Kernel back to idle | ⬜ |

---

## Technical Notes

### Selectors Reference (code-server/VS Code)
| Element | Selector |
|---------|----------|
| Workbench | `.monaco-workbench` |
| Activity bar | `.activitybar` |
| Explorer | `.explorer-viewlet` |
| Quick Open | `.quick-input-widget` |
| Notebook editor | `.notebook-editor` |
| Code cell | `.code-cell-row` |
| Markdown cell | `.markdown-cell-row` |
| Cell editor (Monaco) | `.cell-editor-part .monaco-editor` |
| Run cell button | `.cell-run-button` |
| Kernel status | `.kernel-status` |
| Tab by name | `.tab:has-text("filename")` |

### Keyboard Shortcuts
| Action | Shortcut |
|--------|----------|
| Quick Open | Ctrl+P |
| Run cell | Shift+Enter |
| Run cell, stay | Ctrl+Enter |
| Move to next cell | ArrowDown (in command mode) |
| Enter edit mode | Enter |
| Exit to command mode | Escape |
| Add cell below | B (in command mode) |
| Delete cell | DD (in command mode) |

### Common Pitfalls
1. **Clicking markdown vs code cells** - Use `.code-cell-row` not just any cell
2. **Element outside viewport** - Use `locator().click()` which auto-scrolls
3. **Kernel not ready** - Wait for kernel status to show "idle"
4. **Cell execution timing** - Wait for output element to appear, not just time delay
5. **Quick Open timing** - Wait for list entry to appear before pressing Enter

---

## Progress Log

### 2026-01-21
- [x] Created Docker-based recording environment
- [x] Installed Jupyter extension in container
- [x] Installed Python and ipykernel in container
- [x] Created initial duckdb-magic.spec.ts test
- [x] Fixed Welcome page issue (disabled via settings.json)
- [x] Fixed notebook opening via Quick Open
- [ ] **CURRENT BLOCKER:** Script clicks on wrong cell type (markdown instead of code)
- [ ] **CURRENT BLOCKER:** Script sends wrong command (newline instead of run cell)

### Next Steps
1. Fix cell selection to target `.code-cell-row` specifically
2. Use Shift+Enter to run cells
3. Add explicit waits for cell execution output
4. Verify kernel selection works
5. Complete Demo 1 recording
6. Move on to Demo 2

---

## Output Files

| Demo | Video | GIF | Screenshot | Status |
|------|-------|-----|------------|--------|
| DuckDB SQL Magic | `duckdb-demo-final.webm` | - | - | 🔴 Broken |
| Quick Start | - | - | - | ⬜ Not Started |
| Asset Rendering | - | - | - | ⬜ Not Started |
| Cell Manipulation | - | - | - | ⬜ Not Started |
| Emergency Stop | - | - | - | ⬜ Not Started |

---

## Success Criteria

A demo is considered **complete** when:
1. ✅ Video shows the intended workflow from start to finish
2. ✅ All actions are visible and understandable
3. ✅ No error dialogs or unexpected UI appears
4. ✅ Output/results are clearly shown
5. ✅ Video is under 60 seconds (or appropriately edited)
6. ✅ GIF version created for documentation
7. ✅ Reviewed and approved by maintainer
