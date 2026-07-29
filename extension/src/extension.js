const vscode = require("vscode");

class RunItem extends vscode.TreeItem {
  constructor(label, description, icon) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.description = description;
    this.iconPath = new vscode.ThemeIcon(icon);
    this.contextValue = "ticket2patchRun";
  }
}

class RunsProvider {
  constructor() {
    this._onDidChangeTreeData = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    this.runs = [];
  }

  refresh() {
    this._onDidChangeTreeData.fire();
  }

  addPendingRun(issueKey) {
    this.runs.unshift(
      new RunItem(issueKey, "Backend connection pending", "clock")
    );
    this.refresh();
  }

  getTreeItem(item) {
    return item;
  }

  getChildren() {
    return this.runs;
  }

  dispose() {
    this._onDidChangeTreeData.dispose();
  }
}

function activate(context) {
  const runsProvider = new RunsProvider();
  const runsView = vscode.window.createTreeView("ticket2patch.runs", {
    treeDataProvider: runsProvider,
    showCollapseAll: false
  });

  const statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    50
  );
  statusBar.name = "Ticket2Patch";
  statusBar.text = "$(tools) Ticket2Patch";
  statusBar.tooltip = "Open the Ticket2Patch runs view";
  statusBar.command = "workbench.view.extension.ticket2patch";
  statusBar.show();

  const startRun = vscode.commands.registerCommand(
    "ticket2patch.startRun",
    async () => {
      const issueKey = await vscode.window.showInputBox({
        title: "Start Ticket2Patch",
        prompt: "Enter a Jira issue key",
        placeHolder: "PAY-142",
        validateInput(value) {
          const normalized = value.trim().toUpperCase();
          return /^[A-Z][A-Z0-9_]*-\d+$/.test(normalized)
            ? undefined
            : "Enter a Jira key such as PAY-142.";
        }
      });

      if (!issueKey) {
        return;
      }

      const normalizedIssueKey = issueKey.trim().toUpperCase();
      runsProvider.addPendingRun(normalizedIssueKey);

      const backendUrl = vscode.workspace
        .getConfiguration("ticket2patch")
        .get("backendUrl");

      void vscode.window.showInformationMessage(
        `${normalizedIssueKey} added to the local view. Backend API integration at ${backendUrl} is the next step.`
      );
    }
  );

  const refreshRuns = vscode.commands.registerCommand(
    "ticket2patch.refresh",
    () => {
      runsProvider.refresh();
      void vscode.window.showInformationMessage(
        "Ticket2Patch view refreshed. Backend synchronization is not implemented yet."
      );
    }
  );

  const openSettings = vscode.commands.registerCommand(
    "ticket2patch.openSettings",
    () => {
      void vscode.commands.executeCommand(
        "workbench.action.openSettings",
        "@ext:ticket2patch.ticket2patch"
      );
    }
  );

  context.subscriptions.push(
    runsProvider,
    runsView,
    statusBar,
    startRun,
    refreshRuns,
    openSettings
  );
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
};
