function run() {
  var app = Application.currentApplication();
  app.includeStandardAdditions = true;

  var shellScriptPath = "/Users/gustavocaloi/Documents/dev/busca-aereo/scripts/executar_no_automator.sh";
  var commandText = "/bin/zsh " + shellScriptPath;

  try {
    app.doShellScript(commandText);
  } catch (error) {
    app.displayDialog(
      "Falha ao executar a automacao.\n\n" + error.toString(),
      {buttons: ["OK"], defaultButton: "OK", withIcon: "stop"}
    );
    throw error;
  }
}
