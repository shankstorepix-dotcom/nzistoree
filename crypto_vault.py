"""End-to-end application-layer authenticated encryption (AES-256-GCM) for NziStore."""
import base64
import ctypes
import ctypes.util
import hashlib
import hmac
import secrets

PREFIX_GCM = 'enc:gcm1:'
PREFIX_MAC = 'enc:mac1:'

_libcrypto_name = ctypes.util.find_library('crypto')
_libcrypto = ctypes.CDLL(_libcrypto_name) if _libcrypto_name else None

EVP_CTRL_GCM_SET_IVLEN = 0x9
EVP_CTRL_GCM_GET_TAG = 0x10
EVP_CTRL_GCM_SET_TAG = 0x11

if _libcrypto is not None:
    _libcrypto.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
    _libcrypto.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
    _libcrypto.EVP_aes_256_gcm.restype = ctypes.c_void_p
    _libcrypto.EVP_EncryptInit_ex.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    _libcrypto.EVP_EncryptUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p, ctypes.c_int]
    _libcrypto.EVP_EncryptFinal_ex.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    _libcrypto.EVP_DecryptInit_ex.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    _libcrypto.EVP_DecryptUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p, ctypes.c_int]
    _libcrypto.EVP_DecryptFinal_ex.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    _libcrypto.EVP_CIPHER_CTX_ctrl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]


def derive_subkey(master_key_hex: str, context: str) -> bytes:
    """HKDF-SHA256 subkey derivation bound to a specific domain context."""
    ikm = bytes.fromhex(master_key_hex) if len(master_key_hex) == 64 else hashlib.sha256(master_key_hex.encode()).digest()
    prk = hmac.new(b'nzistore-hkdf-salt-v1', ikm, hashlib.sha256).digest()
    info = f'nzistore:aead:v1:{context}'.encode('utf-8') + b'\x01'
    return hmac.new(prk, info, hashlib.sha256).digest()


def _aes256_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    ctx = _libcrypto.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError('Falha ao inicializar contexto criptográfico.')
    try:
        cipher = _libcrypto.EVP_aes_256_gcm()
        if _libcrypto.EVP_EncryptInit_ex(ctx, cipher, None, None, None) != 1:
            raise RuntimeError('Falha em EVP_EncryptInit_ex.')
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(nonce), None) != 1:
            raise RuntimeError('Falha ao definir IV GCM.')
        if _libcrypto.EVP_EncryptInit_ex(ctx, None, None, key, nonce) != 1:
            raise RuntimeError('Falha ao definir chave/nonce GCM.')
        outlen = ctypes.c_int(0)
        if aad:
            if _libcrypto.EVP_EncryptUpdate(ctx, None, ctypes.byref(outlen), aad, len(aad)) != 1:
                raise RuntimeError('Falha ao autenticar AAD.')
        outbuf = ctypes.create_string_buffer(len(plaintext) + 16)
        if _libcrypto.EVP_EncryptUpdate(ctx, outbuf, ctypes.byref(outlen), plaintext, len(plaintext)) != 1:
            raise RuntimeError('Falha ao cifrar payload.')
        total = outlen.value
        finlen = ctypes.c_int(0)
        if _libcrypto.EVP_EncryptFinal_ex(ctx, ctypes.byref(outbuf, total), ctypes.byref(finlen)) != 1:
            raise RuntimeError('Falha ao finalizar cifra GCM.')
        total += finlen.value
        tag = ctypes.create_string_buffer(16)
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, 16, tag) != 1:
            raise RuntimeError('Falha ao obter tag GCM.')
        return outbuf.raw[:total], tag.raw
    finally:
        _libcrypto.EVP_CIPHER_CTX_free(ctx)


def _aes256_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, aad: bytes) -> bytes:
    ctx = _libcrypto.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError('Falha ao inicializar contexto criptográfico.')
    try:
        cipher = _libcrypto.EVP_aes_256_gcm()
        if _libcrypto.EVP_DecryptInit_ex(ctx, cipher, None, None, None) != 1:
            raise ValueError('Erro de inicialização GCM.')
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, len(nonce), None) != 1:
            raise ValueError('IV inválido.')
        if _libcrypto.EVP_DecryptInit_ex(ctx, None, None, key, nonce) != 1:
            raise ValueError('Chave/nonce inválidos.')
        outlen = ctypes.c_int(0)
        if aad:
            if _libcrypto.EVP_DecryptUpdate(ctx, None, ctypes.byref(outlen), aad, len(aad)) != 1:
                raise ValueError('AAD inválido.')
        outbuf = ctypes.create_string_buffer(len(ciphertext) + 16)
        if _libcrypto.EVP_DecryptUpdate(ctx, outbuf, ctypes.byref(outlen), ciphertext, len(ciphertext)) != 1:
            raise ValueError('Falha ao decifrar payload.')
        total = outlen.value
        tag_buf = ctypes.create_string_buffer(tag, 16)
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, 16, tag_buf) != 1:
            raise ValueError('Tag GCM inválida.')
        finlen = ctypes.c_int(0)
        if _libcrypto.EVP_DecryptFinal_ex(ctx, ctypes.byref(outbuf, total), ctypes.byref(finlen)) != 1:
            raise ValueError('Autenticação criptográfica GCM falhou (dados adulterados).')
        total += finlen.value
        return outbuf.raw[:total]
    finally:
        _libcrypto.EVP_CIPHER_CTX_free(ctx)


def seal(plaintext: str, master_key_hex: str, context: str = 'default') -> str:
    """Encrypts and authenticates a string using AES-256-GCM with a random 96-bit nonce."""
    if not isinstance(plaintext, str):
        raise TypeError('O valor precisa ser texto.')
    if plaintext.startswith((PREFIX_GCM, PREFIX_MAC)):
        return plaintext
    raw = plaintext.encode('utf-8')
    subkey = derive_subkey(master_key_hex, context)
    aad = f'nzistore:aad:{context}'.encode('utf-8')
    nonce = secrets.token_bytes(12)
    if _libcrypto is not None:
        ciphertext, tag = _aes256_gcm_encrypt(subkey, nonce, raw, aad)
        blob = nonce + tag + ciphertext
        return PREFIX_GCM + base64.urlsafe_b64encode(blob).decode('ascii')
    stream = hashlib.shake_256(subkey + nonce + aad).digest(len(raw))
    ciphertext = bytes(a ^ b for a, b in zip(raw, stream))
    tag = hmac.new(subkey, nonce + aad + ciphertext, hashlib.sha256).digest()[:16]
    return PREFIX_MAC + base64.urlsafe_b64encode(nonce + tag + ciphertext).decode('ascii')


def unseal(value: str, master_key_hex: str, context: str = 'default', allow_legacy: bool = True) -> str:
    """Verifies the authentication tag and decrypts an AES-256-GCM envelope."""
    if value is None or not isinstance(value, str):
        return value
    if value.startswith(PREFIX_GCM):
        blob = base64.urlsafe_b64decode(value[len(PREFIX_GCM):].encode('ascii'))
        if len(blob) < 28:
            raise ValueError('Envelope criptográfico truncado.')
        nonce, tag, ciphertext = blob[:12], blob[12:28], blob[28:]
        subkey = derive_subkey(master_key_hex, context)
        aad = f'nzistore:aad:{context}'.encode('utf-8')
        return _aes256_gcm_decrypt(subkey, nonce, ciphertext, tag, aad).decode('utf-8')
    if value.startswith(PREFIX_MAC):
        blob = base64.urlsafe_b64decode(value[len(PREFIX_MAC):].encode('ascii'))
        if len(blob) < 28:
            raise ValueError('Envelope criptográfico truncado.')
        nonce, tag, ciphertext = blob[:12], blob[12:28], blob[28:]
        subkey = derive_subkey(master_key_hex, context)
        aad = f'nzistore:aad:{context}'.encode('utf-8')
        expected = hmac.new(subkey, nonce + aad + ciphertext, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected):
            raise ValueError('Autenticação criptográfica falhou.')
        stream = hashlib.shake_256(subkey + nonce + aad).digest(len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, stream)).decode('utf-8')
    if allow_legacy:
        return value
    raise ValueError('Valor não criptografado rejeitado.')
