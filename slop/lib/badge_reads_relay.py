def wire(app, _loopback, _relay) -> None:
    async def start_badge_reads() -> None:
        import badge_reads
        badge_reads.start()

    app.on_event("startup")(start_badge_reads)
