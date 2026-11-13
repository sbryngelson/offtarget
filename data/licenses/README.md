# data/licenses/

This directory holds the licence and copyright texts of the third-party programs that `data/bench/` carries or builds on: the harvested test and example programs, the application corpus, and HeCBench. The files are copied verbatim from each upstream repository and named `<owner>__<repository>.<original file name>`. `Apache-2.0.txt`, `MIT-AMD.txt` and `MIT-Intel.txt` are the standard texts with the copyright line the files carry. They are used where the cached checkout has no licence file, and the notices file says so under "Reconstructed texts".

`THIRD_PARTY_NOTICES.md` is the index. For each source repository it gives the pinned commit, the licence, the copyright holder, the number of files in the tree and the licence text here that covers them. It also states what the harvest changed in each file. The two copyleft texts (GPL-3.0 and CC BY-SA 4.0) are not here. They sit beside the files they cover, in `data/bench/harvest2/copyleft/`.

When a program from a new source enters `data/bench/`, add its licence text here and a row to the notices. These texts do not cover the catalog's own code or generated programs.
