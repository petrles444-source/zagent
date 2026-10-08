
 =========================
   NOVA STUDIO JAVASCRIPT
   ========================= 


 Плавное появление блоков при прокрутке 


const animatedElements = document.querySelectorAll(
`
.service-card,
.process-card,
.portfolio-card,
.price-card,
.review-card,
.trust-item,
.stat,
.faq-item
`
);



animatedElements.forEach((element)={

    element.classList.add(animate);

});




const observer = new IntersectionObserver(
(entries)={


entries.forEach((entry)={


if(entry.isIntersecting){


entry.target.classList.add(visible);


}


});


},
{
    threshold0.15
}
);




animatedElements.forEach((element)={


observer.observe(element);


});








 =========================
   MOBILE MENU
========================= 


const menuButton = document.querySelector(.mobile-menu);

const navigation = document.querySelector(.nav);



if(menuButton){


menuButton.addEventListener(click,()={


navigation.classList.toggle(active);


menuButton.classList.toggle(open);



});


}








 =========================
   HEADER EFFECT
========================= 


const header = document.querySelector(.header);



window.addEventListener(scroll,()={


if(window.scrollY  50){


header.classList.add(scrolled);


}else{


header.classList.remove(scrolled);


}


});








 =========================
   SMOOTH BUTTON SCROLL
========================= 


document.querySelectorAll('a[href^=#]').forEach(link={


link.addEventListener(click,function(e){


const target=document.querySelector(
this.getAttribute(href)
);



if(target){


e.preventDefault();


target.scrollIntoView({

behaviorsmooth

});


}



});


});








 =========================
   FORM HANDLING
========================= 


const form=document.querySelector(.contact-form);



if(form){


form.addEventListener(submit,(event)={


event.preventDefault();



const inputs=form.querySelectorAll(
input, textarea
);



let filled=true;



inputs.forEach(input={


if(input.value.trim()===){


filled=false;


}


});




if(!filled){


showMessage(
Пожалуйста, заполните все поля
);


return;


}



showMessage(
Спасибо! Заявка отправлена. Мы скоро свяжемся с вами.
);



form.reset();



});


}








 =========================
   MESSAGE WINDOW
========================= 


function showMessage(text){


const message=document.createElement(div);



message.className=notification;


message.innerHTML=text;



document.body.appendChild(message);




setTimeout(()={


message.classList.add(show);


},100);




setTimeout(()={


message.classList.remove(show);



setTimeout(()={


message.remove();


},400);



},3500);



}








 =========================
   PARALLAX HERO
========================= 


const heroImage=document.querySelector(.hero-image img);



window.addEventListener(mousemove,(event)={


if(!heroImage) return;



const x=(window.innerWidth2-event.clientX)50;

const y=(window.innerHeight2-event.clientY)50;



heroImage.style.transform=
`
translate(${x}px,${y}px)
`;



});








 =========================
   COUNTER ANIMATION
========================= 


const counters=document.querySelectorAll(.stat strong);



let counterStarted=false;



function startCounters(){


if(counterStarted) return;



const section=document.querySelector(.statistics);



if(!section) return;



const position=
section.getBoundingClientRect().top;



if(position  window.innerHeight){



counterStarted=true;



counters.forEach(counter={


const value=counter.innerText;



const number=parseInt(
value
);



let current=0;



const interval=setInterval(()={


current++;



counter.innerText=
current+
(value.includes(+)  +  );



if(current=number){


clearInterval(interval);


}


},30);



});



}


}




window.addEventListener(
scroll,
startCounters
);



startCounters();








 =========================
   IMAGE LAZY EFFECT
========================= 


const images=document.querySelectorAll(img);



images.forEach(image={


image.addEventListener(
load,
()={


image.classList.add(loaded);


});


});
