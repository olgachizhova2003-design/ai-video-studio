'use strict';
document.addEventListener('click',async event=>{
  const action=event.target.closest('[data-online-action]')?.dataset.onlineAction;if(!action)return;
  try{
    if(action==='refresh'){await saveWorkspace();await reload();render();toast('Общая библиотека и история обновлены');}
    if(action==='logout'){
      await saveWorkspace();const me=await fetch('/auth/me',{credentials:'same-origin'});const data=await me.json();
      const result=await fetch('/auth/logout',{method:'POST',credentials:'same-origin',headers:{'X-Studio-Request':'local','X-CSRF-Token':data.csrf}});if(!result.ok)throw Error('Не удалось выйти');window.location.assign('/login');
    }
  }catch(error){toast(error.message);}
});
