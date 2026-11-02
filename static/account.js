'use strict';
const $ = selector => document.querySelector(selector);
let csrf = '';
async function api(path, body) {
  const response = await fetch('/api/auth/' + path, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {})
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Não foi possível concluir.');
  return result;
}
function show(logged, otpMode = false) {
  $('#auth-form').hidden = logged || otpMode;
  $('#social-auth').hidden = logged || otpMode;
  if ($('#otp-form')) $('#otp-form').hidden = logged || !otpMode;
  $('#account').hidden = !logged;
  document.body.classList.toggle('account-connected-view',logged);
  $('#account-shell').setAttribute('aria-busy','false');
  $('#account-title').textContent=logged?'Minha conta':'Entre na sua conta';
  $('#account-subtitle').textContent=logged?'Gerencie seu acesso e acompanhe suas compras.':'Entre para acompanhar suas compras e falar com o suporte.';
  if(!logged){$('#profile-form').reset();$('#profile-title').textContent='Sua conta';$('#profile-email').textContent='';$('#profile-message').textContent='';$('#password-form').reset();$('#account-security').open=false;}
}
function renderProfile(profile){
  $('#profile-title').textContent=profile.nickname;
  $('#profile-email').textContent=profile.email;
  $('#profile-nickname').value=profile.nickname;
  const next=profile.nickname_change_available_at*1000;
  $('#nickname-help').textContent=next>Date.now()?'Próxima alteração disponível em '+new Date(next).toLocaleString('pt-BR')+'. Seu login continua sendo pelo email.':'Você pode alterar seu nome de usuário uma vez a cada 24 horas. Seu login continua sendo pelo email.';
}
$('#profile-form').onsubmit=async event=>{
  event.preventDefault();const button=$('#save-nickname');button.disabled=true;$('#profile-message').textContent='';
  try{const session=await api('me');csrf=session.csrf;const profile=await api('profile',{nickname:$('#profile-nickname').value.trim()});renderProfile(profile);$('#profile-message').textContent='Nome de usuário salvo.';}
  catch(error){$('#profile-message').textContent=error.message;}
  finally{button.disabled=false;}
};
async function refresh() {
  try {
    const result = await api('me');
    csrf = result.csrf;
    renderProfile(result);
    show(true);window.scrollTo({top:0,behavior:'instant'});
  } catch {
    try {
      const rotated = await api('refresh', {});
      csrf = rotated.csrf;
      renderProfile(await api('me'));
      show(true);window.scrollTo({top:0,behavior:'instant'});
    } catch {
      csrf = '';
      show(false);
    }
  }
}
async function authenticate(register) {
  $('#message').textContent = '';
  try {
    const email = $('#email').value.trim();
    const password = $('#password').value;
    if (register) {
      if (password.length < 8 || password.length > 24) {
        $('#message').textContent = 'Crie uma senha com caracteres entre 8 e 24 caracteres.';
        return;
      }
    }
    const body = { email, password };
    const result = await api(register ? 'register' : 'login', body);
    $('#password').value = '';
    if (result.verification_required) {
      $('#otp-email').value = email;
      $('#otp-code').value = '';
      show(false, true);
      $('#otp-code').focus();
      $('#message').textContent = 'Enviamos um código de 6 dígitos para o seu e-mail.';
    } else await refresh();
  } catch (error) { $('#message').textContent = error.message; }
}
$('#auth-form').onsubmit = event => { event.preventDefault(); authenticate(false); };
$('#register').onclick = () => { if ($('#auth-form').reportValidity()) authenticate(true); };
if ($('#cancel-otp')) {
  $('#cancel-otp').onclick = () => { $('#message').textContent = ''; show(false, false); };
}
if ($('#otp-form')) {
  $('#otp-form').onsubmit = async event => {
    event.preventDefault();
    $('#message').textContent = '';
    try {
      await api('verify-otp', { email: $('#otp-email').value.trim(), otp: $('#otp-code').value.trim() });
      $('#otp-code').value = '';
      await refresh();
    } catch (error) { $('#message').textContent = error.message; }
  };
}
if ($('#resend-otp')) {
  $('#resend-otp').onclick = async () => {
    $('#message').textContent = '';
    const email = $('#otp-email').value.trim();
    if (!email) { $('#message').textContent = 'Informe seu e-mail.'; return; }
    try {
      await api('resend-otp', { email });
      $('#message').textContent = 'Se a conta aguardar verificação, um novo código foi enviado. Aguarde 60 segundos antes de reenviar.';
    } catch (error) { $('#message').textContent = error.message; }
  };
}
$('#logout').onclick = async () => {
  const button=$('#logout');button.disabled=true;
  try { await api('logout', {}); csrf = ''; show(false); $('#auth-form').reset();$('#message').textContent='Você saiu da conta.';$('#email').focus(); }
  catch (error) { $('#message').textContent = error.message; }
  finally { button.disabled=false; }
};
$('.account-nav a[href="#account-security"]').onclick=()=>{$('#account-security').open=true;};
$('#password-form').onsubmit = async event => {
  event.preventDefault();
  const nextPassword = $('#new-password').value;
  if (nextPassword.length < 8 || nextPassword.length > 24) {
    $('#message').textContent = 'Crie uma senha com caracteres entre 8 e 24 caracteres.';
    return;
  }
  try {
    await api('password', { currentPassword: $('#current').value, password: nextPassword });
    $('#password-form').reset(); csrf = ''; show(false);
    $('#message').textContent = 'Senha alterada. Entre novamente.';
  } catch (error) { $('#message').textContent = error.message; }
};
refresh();

const oauthErrors = {
  not_configured: 'As credenciais OAuth deste provedor ainda não foram configuradas no servidor (.env). Entre com e-mail ou configure GOOGLE_CLIENT_ID / DISCORD_CLIENT_ID.',
  cancelled: 'A autenticação social foi cancelada.',
  invalid_state: 'A sessão de login social expirou. Tente novamente.',
  exchange_failed: 'Não foi possível validar sua conta no provedor. Tente novamente.',
  unverified_email: 'Sua conta precisa ter um e-mail verificado no provedor para entrar.',
  admin_forbidden: 'Contas administrativas devem entrar exclusivamente pelo painel /dashboard com senha e PIN.'
};
const params = new URLSearchParams(location.search);
const oauthError = params.get('oauth_error');
if (oauthError) {
  const text = oauthErrors[oauthError] || 'Não foi possível concluir o login social.';
  if ($('#bssocStatus')) $('#bssocStatus').textContent = text;
  $('#message').textContent = text;
  history.replaceState(null, '', '/conta');
}

document.querySelectorAll('.bssoc-btn').forEach(button => {
  button.addEventListener('click', () => {
    const provider = (button.dataset.oauth || button.dataset.provider || '').toLowerCase();
    if (provider === 'google' || provider === 'discord') {
      $('#bssocStatus').textContent = `Redirecionando para ${button.dataset.provider}…`;
      location.href = `/api/auth/oauth/${provider}/start`;
    }
  });
});

$('#forgot-password').onclick=()=>{$('#auth-form').hidden=true;$('#social-auth').hidden=true;$('#reset-form').hidden=false;$('#reset-email').value=$('#email').value;$('#reset-email').focus();};
$('#reset-cancel').onclick=()=>{$('#reset-form').hidden=true;$('#reset-form').reset();show(false);};
$('#reset-send').onclick=async()=>{const b=$('#reset-send');if(!$('#reset-email').reportValidity())return;b.disabled=true;try{const r=await api('forgot-password',{email:$('#reset-email').value.trim()});$('#reset-message').textContent=r.message;}catch(e){$('#reset-message').textContent=e.message;}finally{b.disabled=false;}};
$('#reset-form').onsubmit=async e=>{e.preventDefault();const b=$('#reset-form button[type="submit"]');b.disabled=true;try{await api('reset-password',{email:$('#reset-email').value.trim(),code:$('#reset-code').value.trim(),password:$('#reset-password').value});csrf='';$('#reset-form').hidden=true;$('#reset-form').reset();show(false);$('#message').textContent='Senha atualizada! Entre com sua nova senha.';}catch(error){$('#reset-message').textContent=error.message;}finally{b.disabled=false;}};
