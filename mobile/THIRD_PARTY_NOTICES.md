# Android third-party notices

This file and the accompanying `licenses/` directory must accompany the Android APK distribution.
EYEPQC's original code is covered by the root [MIT License](../LICENSE). These terms cover the named third-party components under their respective licenses.
The Android 0.9.0 distribution uses the dependency versions below, unchanged from the previously verified Gradle `debugRuntimeClasspath`.
Dependencies are used unmodified; the separate JVM test harness uses Kotlin 1.8.21, while the APK resolves Kotlin 1.9.10.

## Apache License 2.0 components

A copy of the license is provided in [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt).
Source and original licensing information:

- OkHttp 4.12.0 — Square, Inc. and contributors; [source/license](https://github.com/square/okhttp/tree/parent-4.12.0).
- Okio / okio-jvm 3.6.0 — Square, Inc. and contributors; [source/license](https://github.com/square/okio/tree/parent-3.6.0).
- Kotlin stdlib / common / jdk7 / jdk8 1.9.10 — JetBrains s.r.o. and Kotlin contributors; [source/license](https://github.com/JetBrains/kotlin/tree/v1.9.10/license).
- JetBrains annotations 13.0 — JetBrains s.r.o. and contributors; [source/license](https://github.com/JetBrains/java-annotations).
- Gson 2.11.0 — Google Inc. and contributors; [source/license](https://github.com/google/gson/tree/gson-parent-2.11.0).
- Error Prone annotations 2.27.0 — Google Inc. and contributors; [source/license](https://github.com/google/error-prone/tree/v2.27.0).

## Bouncy Castle bcprov-jdk18on 1.81

Source: [bc-java r1rv81](https://github.com/bcgit/bc-java/tree/r1rv81).
The following notice is reproduced from `org.bouncycastle.LICENSE` in the exact dependency JAR:

```text
Copyright (c) 2000-2023 The Legion of the Bouncy Castle Inc. (https://www.bouncycastle.org)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

## Public Suffix List in OkHttp

The following notice is reproduced from `okhttp3/internal/publicsuffix/NOTICE` in okhttp 4.12.0:

```text
Note that publicsuffixes.gz is compiled from The Public Suffix List:
https://publicsuffix.org/list/public_suffix_list.dat

It is subject to the terms of the Mozilla Public License, v. 2.0:
https://mozilla.org/MPL/2.0/
```

A copy of MPL 2.0 is provided in [licenses/MPL-2.0.txt](licenses/MPL-2.0.txt).
The corresponding source data and generation code for the distributed OkHttp version are available at
[OkHttp 4.12.0 publicsuffix resources](https://github.com/square/okhttp/tree/parent-4.12.0/okhttp/src/main/resources/okhttp3/internal/publicsuffix)
and [PublicSuffixDatabase](https://github.com/square/okhttp/blob/parent-4.12.0/okhttp/src/main/kotlin/okhttp3/internal/publicsuffix/PublicSuffixDatabase.kt).
The upstream uncompressed list is available from the Public Suffix List link above.
