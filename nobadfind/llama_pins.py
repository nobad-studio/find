"""The pinned llama.cpp release (tag b12602, tools/vision_bench/models.json): each runtime zip and the DLLs kept from it.

Only the DLLs Find loads: ggml, ggml-base, the ggml-cpu-* variants, ggml-vulkan (Vulkan zip), libomp, llama and
mtmd (their PE import tables name nothing else from the zip; checked with pefile on b12602). Not kept: the llama.cpp
programs' bodies (llama-server-impl, llama-cli-impl, llama-common and the other *-impl.dll tools), ggml-rpc.dll (a
network backend; maintainer ruling: never kept. b12602's zips do ship it, with ggml-rpc-server.exe) and every .exe.
What isn't pinned is never unpacked. name: (size, SHA-256).
"""

TAG = 'b12602'

CPU_ZIP = ('llama-b12602-bin-win-cpu-x64.zip', 'https://github.com/ggml-org/llama.cpp/releases/download/b12602/llama-b12602-bin-win-cpu-x64.zip', 25012065, '9957dab2f52e2599b85921ef3e2661287c1f3ad302bc0be07992e915cc6f7392')  # name, url, size, SHA-256
CPU_DLLS = {
    'ggml-base.dll': (840704, '2a08f67e9fdafcc2ab879f7d4a384d608043de2a7c7ed815b89d823ce0395e0b'),
    'ggml-cpu-alderlake.dll': (1496576, '5f6bfe1a686fe7114e8f3be4cd1d59165c58857b24f8a4d2d74c90b233d535bd'),
    'ggml-cpu-cannonlake.dll': (1731584, '92bdcd928c43dc87df4f062ee6970a6121e8e3f1523e8441711c1ff8a8e24662'),
    'ggml-cpu-cascadelake.dll': (1700352, '91a5fad45e3baec15452c537bb41e5d573829eb0558590a73b1e66657de156f3'),
    'ggml-cpu-cooperlake.dll': (1709568, '72ef56afdeff8993b1d997a9e9a79216350872937c60f2e7375ef76f9bcc43ec'),
    'ggml-cpu-haswell.dll': (1503232, '4725a4fad824027915cdd4c3b1ad837acca59041941a500f414b6347a1afeba6'),
    'ggml-cpu-icelake.dll': (1709056, '96eab2d826b76d07820dccac8b4c53124df50960b7da6322e3f41cc8252ea895'),
    'ggml-cpu-ivybridge.dll': (1370624, '736abc684ec789d627192e38095016ecae53bae13e96763750eec50c3f59030c'),
    'ggml-cpu-piledriver.dll': (1365504, 'e46d1e0ef9b598109a6110f04f6a22fd57e6ca0d1db7a98b0ec078a10f438b47'),
    'ggml-cpu-sandybridge.dll': (1340416, '9b07f136f1d18d4dec9bf0d0013c40f4d5fc5dbd737c4739435ca699bf6e4766'),
    'ggml-cpu-sapphirerapids.dll': (1988608, '36618500ef93e09ab9353fcc29ece0b55b3d5ba74aa272400c242505a4fc28b5'),
    'ggml-cpu-skylakex.dll': (1722880, 'aaba52e938da026a9bb19e39510529ba7139d6821016d91f18b7742b8f60e355'),
    'ggml-cpu-sse42.dll': (963584, 'fd89f0f5def60371d078af1fc1efe45f165766da9089c21f74e08aaa9942f535'),
    'ggml-cpu-x64.dll': (956928, '08410b24b8766d97c88aee959dc2a1dd232150697de7a86356f8d02885638b74'),
    'ggml-cpu-zen4.dll': (1718272, 'c92291a836347e8cffdbf375dfbfc47cacdee648eb25643a376891173117ab1c'),
    'ggml.dll': (78848, 'bb62f894d04d5b8cd05db1a76d7f0d5c150002053a701ec8c024ec4a9fd3e931'),
    'libomp.dll': (856064, '1e4222f195d84e7355109d778e751dfe3c085e42c947f7fe3d7853181329dd40'),
    'llama.dll': (3981824, '22ad70fd7e93eaef859b501674511480cfe8c9f004a3c85c57e66999f1d3e972'),
    'mtmd.dll': (3000320, 'a4d931582e6703f032840f1b7e61252401fb2c1fbe7b2e1831a8f140eda1d102'),
}

VULKAN_ZIP = ('llama-b12602-bin-win-vulkan-x64.zip', 'https://github.com/ggml-org/llama.cpp/releases/download/b12602/llama-b12602-bin-win-vulkan-x64.zip', 38857755, '723c13b3bc0759c1d86c09316a06cb549c78702cf3a441de5bff64c27f26fded')  # name, url, size, SHA-256
VULKAN_DLLS = {
    'ggml-base.dll': (840704, '2a08f67e9fdafcc2ab879f7d4a384d608043de2a7c7ed815b89d823ce0395e0b'),
    'ggml-cpu-alderlake.dll': (1496576, '5f6bfe1a686fe7114e8f3be4cd1d59165c58857b24f8a4d2d74c90b233d535bd'),
    'ggml-cpu-cannonlake.dll': (1731584, '92bdcd928c43dc87df4f062ee6970a6121e8e3f1523e8441711c1ff8a8e24662'),
    'ggml-cpu-cascadelake.dll': (1700352, '91a5fad45e3baec15452c537bb41e5d573829eb0558590a73b1e66657de156f3'),
    'ggml-cpu-cooperlake.dll': (1709568, '72ef56afdeff8993b1d997a9e9a79216350872937c60f2e7375ef76f9bcc43ec'),
    'ggml-cpu-haswell.dll': (1503232, '4725a4fad824027915cdd4c3b1ad837acca59041941a500f414b6347a1afeba6'),
    'ggml-cpu-icelake.dll': (1709056, '96eab2d826b76d07820dccac8b4c53124df50960b7da6322e3f41cc8252ea895'),
    'ggml-cpu-ivybridge.dll': (1370624, '736abc684ec789d627192e38095016ecae53bae13e96763750eec50c3f59030c'),
    'ggml-cpu-piledriver.dll': (1365504, 'e46d1e0ef9b598109a6110f04f6a22fd57e6ca0d1db7a98b0ec078a10f438b47'),
    'ggml-cpu-sandybridge.dll': (1340416, '9b07f136f1d18d4dec9bf0d0013c40f4d5fc5dbd737c4739435ca699bf6e4766'),
    'ggml-cpu-sapphirerapids.dll': (1988608, '36618500ef93e09ab9353fcc29ece0b55b3d5ba74aa272400c242505a4fc28b5'),
    'ggml-cpu-skylakex.dll': (1722880, 'aaba52e938da026a9bb19e39510529ba7139d6821016d91f18b7742b8f60e355'),
    'ggml-cpu-sse42.dll': (963584, 'fd89f0f5def60371d078af1fc1efe45f165766da9089c21f74e08aaa9942f535'),
    'ggml-cpu-x64.dll': (956928, '08410b24b8766d97c88aee959dc2a1dd232150697de7a86356f8d02885638b74'),
    'ggml-cpu-zen4.dll': (1718272, 'c92291a836347e8cffdbf375dfbfc47cacdee648eb25643a376891173117ab1c'),
    'ggml-vulkan.dll': (44866560, '17713b2524b44deec39453805e3884c4f912a14d3640d6a264b482cf69eed11b'),
    'ggml.dll': (78848, 'bb62f894d04d5b8cd05db1a76d7f0d5c150002053a701ec8c024ec4a9fd3e931'),
    'libomp.dll': (856064, '1e4222f195d84e7355109d778e751dfe3c085e42c947f7fe3d7853181329dd40'),
    'llama.dll': (3981824, '22ad70fd7e93eaef859b501674511480cfe8c9f004a3c85c57e66999f1d3e972'),
    'mtmd.dll': (3000320, 'a4d931582e6703f032840f1b7e61252401fb2c1fbe7b2e1831a8f140eda1d102'),
}
