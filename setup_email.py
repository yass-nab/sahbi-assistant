"""One-time setup: lets Sahbi send email from your Gmail. Your App Password is typed here (hidden) and saved encrypted."""
import getpass, sys, webbrowser
import mailer

print('=== Sahbi - Gmail setup ===\n')
print('1. A page opens: https://myaccount.google.com/apppasswords')
print('   (Google needs 2-Step Verification ON for this page to work.)')
print('2. App name: Sahbi  ->  Create  ->  copy the 16-letter password.\n')
webbrowser.open('https://myaccount.google.com/apppasswords')
addr = input('Your Gmail address: ').strip()
pw = getpass.getpass('Paste the 16-letter App Password (hidden, then Enter): ').strip()
print('\nChecking with Gmail...')
try:
    mailer.test_login(addr, pw)
except Exception as e:  # noqa: BLE001
    print(f'Gmail refused it: {e}\nCheck the address / App Password and run this again.')
    input('\nPress Enter to close'); sys.exit(1)
mailer.save(addr, pw)
print('OK! Sahbi can now send email as', addr)
print('Saved encrypted (Windows DPAPI) in', mailer.CONF)
print('To remove it later: delete that file, or revoke "Sahbi" at myaccount.google.com/apppasswords.')
input('\nPress Enter to close')
