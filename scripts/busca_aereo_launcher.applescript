on run
	set shellScriptPath to "/Users/gustavocaloi/Documents/dev/busca-aereo/scripts/executar_no_automator.sh"
	set commandText to "/bin/zsh " & quoted form of shellScriptPath
	try
		do shell script commandText
	on error errMsg number errNum
		display dialog "Falha ao executar a automacao." & return & return & errMsg buttons {"OK"} default button "OK" with icon stop
		error number errNum
	end try
end run
