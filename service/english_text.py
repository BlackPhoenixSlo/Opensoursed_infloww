"""Conservative English check for skipping Google on already-English chat text."""
import re
WORDS = frozenset("""
i you me to u and it that my for the a what your are do this of just like want can with how on all have not now im be if love get would ur but know wanna s
good yes see then or when make up out tell time really about let lol t gonna i'm ready right m take show hard going as more one already over at think here from
off too only keep we mm why should back send there did while by go way dont need open give well don't something much even feel thinking its still mmm rn re down
been doing you're okay every say getting got into some waiting babe c ll being mean sure could start deep first stop full had come n https com bad anything don
until today maybe were play these work inside tight little who said never last day always ever exactly talk they best face big everything busy body myself look
sorry any thats wait sent thought after wet till watch i'll part very real access her control mind those next hope done before enjoy again hey name around else
girl game making home made might seeing hear forget please because find oh than it's once wrong nice him w thing wanted feeling top free trying bed has talking
actually better which anymore cant id put perfect hours guess she yeah can't money ask enough morning under use didn't between things other them true imagine
worked both leave ill wants night boy gets honestly welcome cuz fun long does try people most thank thanks he pull times attention fully slow head completely bout
plz where hold giving sending sweet yet that's drop mouth tonight pretty far whole help nothing lets soon lot pass absolutely straight playing slowly saying worth
d new instead sit since life youre whats through yesterday though someone stuff finish answer ofc crazy fingers taking against told kiss asked beautiful message
hi hello hmm haha hahaha lmao omg wow yep nope yea pls thx ty idk btw tho gotta kinda sorta cute sexy hot horny naughty tits cock pussy ass fuck fucking
dick cum daddy mommy onlyfans tip pics pic photo photos pictures picture send sent buy bought pay paid price cheap expensive unlock unlocked tonight tomorrow week
weekend month year years today later soon miss missed missing hun honey darling sweetie gorgeous handsome amazing awesome great fine happy sad tired sleep sleeping
bed wake woke work working job home house car drive eat ate food dinner lunch breakfast drink coffee shower nice cool sounds sound guys girls friend friends
""".split())
_TOK = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)

def words(text: str) -> list[str]:
    return _TOK.findall(text)


def is_english(text: str) -> bool:
    toks = [t.lower() for t in words(text)]
    if not toks:
        return True
    if any(not t.isascii() for t in toks):
        return False
    hits = sum(t in WORDS for t in toks)
    return hits == len(toks) if len(toks) <= 6 else hits > 0.75 * len(toks)
