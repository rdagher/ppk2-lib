# The recording at the top of the README. Needs vhs, a PPK2 wired in
# Source meter mode to a DUT, and `ppk2` on the PATH. Run `just demo`.
# `ppk2 list` is left out: it prints the serial number of the PPK2.
Output docs/img/quickstart.gif
Set Shell zsh
Set FontSize 16
Set Width 1100
Set Height 400
Set TypingSpeed 35ms
Set Theme "GitHub Dark"

Hide
Type "cd $(mktemp -d) && PS1='$ ' && clear"
Enter
Show

Type "ppk2 capture --out boot.csv --seconds 3 --source --vdd 3.3"
Enter
Sleep 7s

Type "head -4 boot.csv"
Enter
Sleep 4s

Type "ppk2 convert boot.csv boot.ppk2"
Enter
Sleep 6s
