"""Mobile remote — phone control surface (Phase R, §R).

A tiny HTTP server inside the app that lets an Android phone control Halcyon
over the local Wi-Fi. The phone side is a web page (no install); the QR code
in PC Settings is the pairing key.

Architecture rule (the safety property that keeps the player intact, §R.4):
the server runs on a dedicated daemon thread and never touches a QObject
directly. Commands are marshalled to the Qt main thread through queued Qt
signals; status flows back through asyncio calls scheduled onto the server
loop from the Qt side. The player's own code paths are never modified — the
remote is a new doorway onto the existing ``AppController`` actions (§4.1).
"""
