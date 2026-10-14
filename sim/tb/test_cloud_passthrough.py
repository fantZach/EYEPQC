"""C/Java suite2 through a raw TCP hop. Not SSH, cloud or Android device evidence."""
import asyncio
import unittest

import test_account_three_end as fixture


class TcpPassthrough:
    def __init__(self, destination):
        self.destination = destination
        self.connections = set()
        self.upload_bytes = self.download_bytes = 0

    async def start(self):
        self.server = await asyncio.start_server(self.forward, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def forward(self, reader, writer):
        owner = asyncio.current_task()
        self.connections.add(owner)
        target_writer = None
        tasks = []
        async def copy(source, destination, counter):
            while True:
                data = await source.read(16384)
                if not data:
                    return
                setattr(self, counter, getattr(self, counter) + len(data))
                destination.write(data)
                await asyncio.wait_for(destination.drain(), 5)
        try:
            target_reader, target_writer = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', self.destination), 5)
            tasks = [asyncio.create_task(copy(reader, target_writer, 'upload_bytes')),
                     asyncio.create_task(copy(target_reader, writer, 'download_bytes'))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for stream in (writer, target_writer):
                if stream is not None:
                    stream.close()
                    try:
                        await asyncio.wait_for(stream.wait_closed(), 5)
                    except (ConnectionError, asyncio.TimeoutError):
                        pass
            self.connections.discard(owner)

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        tasks = list(self.connections)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class CloudPassthrough(fixture.AccountThreeEnd):
    tcp_passthrough = True


if __name__ == '__main__':
    unittest.main(verbosity=2)
