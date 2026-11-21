'use strict';
const form=document.querySelector('#login-form'),button=document.querySelector('#login-submit'),message=document.querySelector('#login-error');
let token;
async function csrf(){const response=await fetch('/auth/csrf',{credentials:'same-origin'});if(!response.ok)throw Error('Сервер временно недоступен');return (await response.json()).csrf;}
token=csrf();token.catch(()=>{});
form.addEventListener('submit',async event=>{
  event.preventDefault();button.disabled=true;button.textContent='Идёт подключение…';message.textContent='';
  try{
    const values=new FormData(form),response=await fetch('/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':await token},body:JSON.stringify({email:values.get('email'),password:values.get('password')})});
    const data=await response.json();if(!response.ok)throw Error(data.error||'Не удалось войти');form.elements.password.value='';window.location.assign('/');
  }catch(error){message.textContent=error.message;message.className='connection-error';token=csrf();token.catch(()=>{});button.disabled=false;button.textContent='Войти в студию';}
});
