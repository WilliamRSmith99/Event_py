import discord

class ExpiringView(discord.ui.View):
    def __init__(self, *, timeout=180):
        super().__init__(timeout=timeout)
        self.message = None  # Reference to the sent message (ephemeral or otherwise)

    async def on_timeout(self):
        # Ephemeral messages can't be deleted, but can be edited to a minimal state
        if self.message:
            try:
                await self.message.edit(content="⏱️ This interaction has expired.", view=None)
            except discord.NotFound:
                pass