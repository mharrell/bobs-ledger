#!/usr/bin/env python3
"""Ed25519 (RFC 8032), vendored so the updater can verify a RELEASE SIGNATURE.

Why this file exists: `update.py` used to check a release zip's sha256 against a
manifest served from the same server as the zip. That proves the download was not
corrupted; it proves nothing about who built it. Whoever holds the release
channel could serve any zip and any matching hash. A signature needs a key the
channel does not hold, and a signature needs Ed25519 -- which the standard
library has no implementation of, and the coach ships with exactly one
dependency (`requests`) on purpose. So the curve lives here.

PROVENANCE: these are the Ed25519 parts of RFC 8032's own reference
implementation (Appendix A, "Ed25519/Ed448 Python Library"), extracted
mechanically from the RFC text -- no constant or formula was retyped by hand.
The Ed448, Ed25519ctx/Ed25519ph, SHA-3/SHAKE and driver sections are dropped;
`rol` (SHA-3 only) is dropped with them. Nothing else was altered.

What was NOT vendored: nothing here is a novel construction, and the module's
job is small -- verify a signature against a PINNED public key, and sign with a
key the publisher keeps offline. `app/tests/test_ed25519.py` pins it to the
RFC's own section 7.1 test vectors, which is what makes the vendoring checkable
rather than a claim.

Fail closed: `verify()` returns False for anything it cannot prove, including a
malformed key, a malformed signature, a point that is not on the curve, and any
exception on the way. A verifier that raises is a verifier that can be made to
say yes by a caller in a hurry.
"""
import hashlib
import os

def sqrt4k3(x,p): return pow(x,(p + 1)//4,p)

#Compute candidate square root of x modulo p, with p = 5 (mod 8).
def sqrt8k5(x,p):
    y = pow(x,(p+3)//8,p)
    #If the square root exists, it is either y or y*2^(p-1)/4.
    if (y * y) % p == x % p: return y
    else:
        z = pow(2,(p - 1)//4,p)
        return (y * z) % p

#Decode a hexadecimal string representation of the integer.

def hexi(s): return int.from_bytes(bytes.fromhex(s),byteorder="big")

def from_le(s): return int.from_bytes(s, byteorder="little")

#A (prime) field element.
class Field:
    #Construct number x (mod p).
    def __init__(self,x,p):
        self.__x=x%p
        self.__p=p
    #Check that fields of self and y are the same.
    def __check_fields(self,y):
        if type(y) is not Field or self.__p!=y.__p:
            raise ValueError("Fields don't match")
    #Field addition.  The fields must match.
    def __add__(self,y):
        self.__check_fields(y)
        return Field(self.__x+y.__x,self.__p)
    #Field subtraction.  The fields must match.
    def __sub__(self,y):
        self.__check_fields(y)
        return Field(self.__p+self.__x-y.__x,self.__p)
    #Field negation.
    def __neg__(self):
        return Field(self.__p-self.__x,self.__p)
    #Field multiplication.  The fields must match.
    def __mul__(self,y):
        self.__check_fields(y)
        return Field(self.__x*y.__x,self.__p)
    #Field division.  The fields must match.
    def __truediv__(self,y):
        return self*y.inv()
    #Field inverse (inverse of 0 is 0).
    def inv(self):
        return Field(pow(self.__x,self.__p-2,self.__p),self.__p)
    #Field square root.  Returns none if square root does not exist.
    #Note: not presently implemented for p mod 8 = 1 case.
    def sqrt(self):
        #Compute candidate square root.
        if self.__p%4==3: y=sqrt4k3(self.__x,self.__p)
        elif self.__p%8==5: y=sqrt8k5(self.__x,self.__p)
        else: raise NotImplementedError("sqrt(_,8k+1)")
        _y=Field(y,self.__p);
        #Check square root candidate valid.
        return _y if _y*_y==self else None
    #Make the field element with the same field as this, but
    #with a different value.
    def make(self,ival): return Field(ival,self.__p)
    #Is the field element the additive identity?
    def iszero(self): return self.__x==0
    #Are field elements equal?
    def __eq__(self,y): return self.__x==y.__x and self.__p==y.__p






    #Are field elements not equal?
    def __ne__(self,y): return not (self==y)
    #Serialize number to b-1 bits.
    def tobytes(self,b):
        return self.__x.to_bytes(b//8,byteorder="little")
    #Unserialize number from bits.
    def frombytes(self,x,b):
        rv=from_le(x)%(2**(b-1))
        return Field(rv,self.__p) if rv<self.__p else None
    #Compute sign of number, 0 or 1.  The sign function
    #has the following property:
    #sign(x) = 1 - sign(-x) if x != 0.
    def sign(self): return self.__x%2

#A point on (twisted) Edwards curve.
class EdwardsPoint:
    #base_field = None
    #x = None
    #y = None
    #z = None
    def initpoint(self, x, y):
        self.x=x
        self.y=y
        self.z=self.base_field.make(1)
    def decode_base(self,s,b):
        #Check that point encoding is the correct length.
        if len(s)!=b//8: return (None,None)
        #Extract signbit.
        xs=s[(b-1)//8]>>((b-1)&7)
        #Decode y.  If this fails, fail.
        y = self.base_field.frombytes(s,b)
        if y is None: return (None,None)
        #Try to recover x.  If it does not exist, or if zero and xs
        #are wrong, fail.
        x=self.solve_x2(y).sqrt()
        if x is None or (x.iszero() and xs!=x.sign()):
            return (None,None)
        #If sign of x isn't correct, flip it.
        if x.sign()!=xs: x=-x
        # Return the constructed point.
        return (x,y)
    def encode_base(self,b):
        xp,yp=self.x/self.z,self.y/self.z
        #Encode y.
        s=bytearray(yp.tobytes(b))
        #Add sign bit of x to encoding.
        if xp.sign()!=0: s[(b-1)//8]|=1<<(b-1)%8
        return s






    def __mul__(self,x):
        r=self.zero_elem()
        s=self
        while x > 0:
            if (x%2)>0:
                r=r+s
            s=s.double()
            x=x//2
        return r
    #Check that two points are equal.
    def __eq__(self,y):
        #Need to check x1/z1 == x2/z2 and similarly for y, so cross
        #multiply to eliminate divisions.
        xn1=self.x*y.z
        xn2=y.x*self.z
        yn1=self.y*y.z
        yn2=y.y*self.z
        return xn1==xn2 and yn1==yn2
    #Check if two points are not equal.
    def __ne__(self,y): return not (self==y)

#A point on Edwards25519.
class Edwards25519Point(EdwardsPoint):
    #Create a new point on the curve.
    base_field=Field(1,2**255-19)
    d=-base_field.make(121665)/base_field.make(121666)
    f0=base_field.make(0)
    f1=base_field.make(1)
    xb=base_field.make(hexi("216936D3CD6E53FEC0A4E231FDD6DC5C692CC76"+\
        "09525A7B2C9562D608F25D51A"))
    yb=base_field.make(hexi("666666666666666666666666666666666666666"+\
        "6666666666666666666666658"))
    #The standard base point.
    @staticmethod
    def stdbase():
        return Edwards25519Point(Edwards25519Point.xb,\
            Edwards25519Point.yb)
    def __init__(self,x,y):
        #Check the point is actually on the curve.
        if y*y-x*x!=self.f1+self.d*x*x*y*y:
            raise ValueError("Invalid point")
        self.initpoint(x, y)
        self.t=x*y
    #Decode a point representation.
    def decode(self,s):
        x,y=self.decode_base(s,256);
        return Edwards25519Point(x, y) if x is not None else None







    #Encode a point representation.
    def encode(self):
        return self.encode_base(256)
    #Construct a neutral point on this curve.
    def zero_elem(self):
        return Edwards25519Point(self.f0,self.f1)
    #Solve for x^2.
    def solve_x2(self,y):
        return ((y*y-self.f1)/(self.d*y*y+self.f1))
    #Point addition.
    def __add__(self,y):
        #The formulas are from EFD.
        tmp=self.zero_elem()
        zcp=self.z*y.z
        A=(self.y-self.x)*(y.y-y.x)
        B=(self.y+self.x)*(y.y+y.x)
        C=(self.d+self.d)*self.t*y.t
        D=zcp+zcp
        E,H=B-A,B+A
        F,G=D-C,D+C
        tmp.x,tmp.y,tmp.z,tmp.t=E*F,G*H,F*G,E*H
        return tmp
    #Point doubling.
    def double(self):
        #The formulas are from EFD (with assumption a=-1 propagated).
        tmp=self.zero_elem()
        A=self.x*self.x
        B=self.y*self.y
        Ch=self.z*self.z
        C=Ch+Ch
        H=A+B
        xys=self.x+self.y
        E=H-xys*xys
        G=A-B
        F=C+G
        tmp.x,tmp.y,tmp.z,tmp.t=E*F,G*H,F*G,E*H
        return tmp
    #Order of basepoint.
    def l(self):
        return hexi("1000000000000000000000000000000014def9dea2f79cd"+\
            "65812631a5cf5d3ed")
    #The logarithm of cofactor.
    def c(self): return 3
    #The highest set bit
    def n(self): return 254
    #The coding length
    def b(self): return 256







    #Validity check (for debugging)
    def is_valid_point(self):
        x,y,z,t=self.x,self.y,self.z,self.t
        x2=x*x
        y2=y*y
        z2=z*z
        lhs=(y2-x2)*z2
        rhs=z2*z2+self.d*x2*y2
        assert(lhs == rhs)
        assert(t*z == x*y)

#PureEdDSA scheme.
#Limitation: only b mod 8 = 0 is handled.
class PureEdDSA:
    #Create a new object.
    def __init__(self,properties):
        self.B=properties["B"]
        self.H=properties["H"]
        self.l=self.B.l()
        self.n=self.B.n()
        self.b=self.B.b()
        self.c=self.B.c()
    #Clamp a private scalar.
    def __clamp(self,a):
        _a = bytearray(a)
        for i in range(0,self.c): _a[i//8]&=~(1<<(i%8))
        _a[self.n//8]|=1<<(self.n%8)
        for i in range(self.n+1,self.b): _a[i//8]&=~(1<<(i%8))
        return _a
    #Generate a key.  If privkey is None, a random one is generated.
    #In any case, the (privkey, pubkey) pair is returned.
    def keygen(self,privkey):
        #If no private key data is given, generate random.
        if privkey is None: privkey=os.urandom(self.b//8)








        #Expand key.
        khash=self.H(privkey,None,None)
        a=from_le(self.__clamp(khash[:self.b//8]))
        #Return the key pair (public key is A=Enc(aB).
        return privkey,(self.B*a).encode()
    #Sign with key pair.
    def sign(self,privkey,pubkey,msg,ctx,hflag):
        #Expand key.
        khash=self.H(privkey,None,None)
        a=from_le(self.__clamp(khash[:self.b//8]))
        seed=khash[self.b//8:]
        #Calculate r and R (R only used in encoded form).
        r=from_le(self.H(seed+msg,ctx,hflag))%self.l
        R=(self.B*r).encode()
        #Calculate h.
        h=from_le(self.H(R+pubkey+msg,ctx,hflag))%self.l
        #Calculate s.
        S=((r+h*a)%self.l).to_bytes(self.b//8,byteorder="little")
        #The final signature is a concatenation of R and S.
        return R+S
    #Verify signature with public key.
    def verify(self,pubkey,msg,sig,ctx,hflag):
        #Sanity-check sizes.
        if len(sig)!=self.b//4: return False
        if len(pubkey)!=self.b//8: return False
        #Split signature into R and S, and parse.
        Rraw,Sraw=sig[:self.b//8],sig[self.b//8:]
        R,S=self.B.decode(Rraw),from_le(Sraw)
        #Parse public key.
        A=self.B.decode(pubkey)
        #Check parse results.
        if (R is None) or (A is None) or S>=self.l: return False
        #Calculate h.
        h=from_le(self.H(Rraw+pubkey+msg,ctx,hflag))%self.l
        #Calculate left and right sides of check eq.
        rhs=R+(A*h)
        lhs=self.B*S
        for i in range(0, self.c):
            lhs = lhs.double()
            rhs = rhs.double()
        #Check eq. holds?
        return lhs==rhs

def Ed25519_inthash(data,ctx,hflag):
    if (ctx is not None and len(ctx) > 0) or hflag:
        raise ValueError("Contexts/hashes not supported")
    return hashlib.sha512(data).digest()







#The base PureEdDSA schemes.
pEd25519=PureEdDSA({\
    "B":Edwards25519Point.stdbase(),\
    "H":Ed25519_inthash\
})


#EdDSA scheme.
class EdDSA:
    #Create a new scheme object, with the specified PureEdDSA base
    #scheme and specified prehash.
    def __init__(self,pure_scheme,prehash):
        self.__pflag = True
        self.__pure=pure_scheme
        self.__prehash=prehash
        if self.__prehash is None:
            self.__prehash = lambda x,y:x
            self.__pflag = False
    # Generate a key.  If privkey is none, it generates a random
    # privkey key, otherwise it uses a specified private key.
    # Returns pair (privkey, pubkey).
    def keygen(self,privkey): return self.__pure.keygen(privkey)








    # Sign message msg using specified key pair.
    def sign(self,privkey,pubkey,msg,ctx=None):
        if ctx is None: ctx=b"";
        return self.__pure.sign(privkey,pubkey,self.__prehash(msg,ctx),\
            ctx,self.__pflag)
    # Verify signature sig on message msg using public key pubkey.
    def verify(self,pubkey,msg,sig,ctx=None):
        if ctx is None: ctx=b"";
        return self.__pure.verify(pubkey,self.__prehash(msg,ctx),sig,\
            ctx,self.__pflag)

# --- the two operations the updater and the publisher actually need ----------

#: Ed25519's sizes, named so a caller never has to guess whether 64 is a
#: signature or a key.
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
PRIVATE_KEY_BYTES = 32

#: "Pure" Ed25519 (no context, no prehash) -- RFC 8032 section 5.1.
_ED25519 = EdDSA(pEd25519, None)


def keygen():
    """(private_key, public_key) -- 32 raw bytes each.

    The private key is the RFC's own `privkey` (a seed), not an expanded
    scalar, so `sign()` takes exactly what this returns and nothing else.
    """
    return _ED25519.keygen(None)


def public_key_of(private_key):
    """The public key for `private_key`, so a pinned key can be re-derived."""
    _, pub = _ED25519.keygen(_seed(private_key))
    return pub


def _seed(private_key):
    seed = bytes(private_key)
    if len(seed) != PRIVATE_KEY_BYTES:
        raise ValueError(f"an Ed25519 private key is {PRIVATE_KEY_BYTES} bytes, "
                         f"got {len(seed)}")
    return seed


def sign(private_key, message):
    """A 64-byte detached signature over `message`."""
    seed = _seed(private_key)
    return _ED25519.sign(seed, public_key_of(seed), bytes(message))


def verify(public_key, message, signature):
    """True only when `signature` is valid for `message` under `public_key`.

    Fail closed, deliberately: every rejection below is a return of False, and
    so is any exception, because the caller's alternative to "proven" is
    "refuse the update", never "proceed anyway".
    """
    try:
        if not isinstance(public_key, (bytes, bytearray)):
            return False
        if not isinstance(signature, (bytes, bytearray)):
            return False
        if not isinstance(message, (bytes, bytearray)):
            return False
        if len(public_key) != PUBLIC_KEY_BYTES:
            return False
        if len(signature) != SIGNATURE_BYTES:
            return False
        return bool(_ED25519.verify(bytes(public_key), bytes(message),
                                    bytes(signature)))
    except Exception:               # noqa: BLE001 - see the docstring
        return False
