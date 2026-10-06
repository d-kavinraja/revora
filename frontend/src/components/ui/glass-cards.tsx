import React, { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { cardData } from '@/lib/utils';
import { useThemeStore } from '@/store/useThemeStore';
import { CheckCircle2, FolderSync, KeyRound, Workflow, Rocket } from 'lucide-react';

gsap.registerPlugin(ScrollTrigger);

interface CardProps {
    id: number;
    title: string;
    description: string;
    index: number;
    totalCards: number;
    color: string;
    isLight: boolean;
}

const getIcon = (id: number) => {
    switch (id) {
        case 1: return <CheckCircle2 size={48} className="text-white" />;
        case 2: return <FolderSync size={48} className="text-white" />;
        case 3: return <KeyRound size={48} className="text-white" />;
        case 4: return <Workflow size={48} className="text-white" />;
        case 5: return <Rocket size={48} className="text-white" />;
        default: return <CheckCircle2 size={48} className="text-white" />;
    }
};

const Card: React.FC<CardProps> = ({ id, title, description, index, totalCards, color, isLight }) => {
    const cardRef = useRef<HTMLDivElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const card = cardRef.current;
        const container = containerRef.current;
        if (!card || !container) return;

        const targetScale = 1 - (totalCards - index) * 0.05;

        // Set initial state
        gsap.set(card, {
            scale: 1,
            transformOrigin: "center top"
        });

        // Create scroll trigger for stacking effect
        ScrollTrigger.create({
            trigger: container,
            start: "top center",
            end: "bottom center",
            scrub: 1,
            onUpdate: (self) => {
                const progress = self.progress;
                const scale = gsap.utils.interpolate(1, targetScale, progress);

                gsap.set(card, {
                    scale: Math.max(scale, targetScale),
                    transformOrigin: "center top"
                });
            }
        });

        return () => {
            ScrollTrigger.getAll().forEach(trigger => trigger.kill());
        };
    }, [index, totalCards]);

    return (
        <div
            ref={containerRef}
            style={{
                height: '100vh',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                position: 'sticky',
                top: 0
            }}
        >
            <div
                ref={cardRef}
                style={{
                    position: 'relative',
                    width: '70%',
                    height: '450px',
                    borderRadius: '24px',
                    isolation: 'isolate',
                    top: `calc(-5vh + ${index * 25}px)`,
                    transformOrigin: 'top'
                }}
                className="card-content"
            >
                {/* Electric Border Effect */}
                <div
                    style={{
                        position: 'absolute',
                        inset: '-3px',
                        borderRadius: '27px',
                        padding: '3px',
                        background: `conic-gradient(
                            from 0deg,
                            transparent 0deg,
                            ${color} 60deg,
                            ${color.replace('0.8', '0.6')} 120deg,
                            transparent 180deg,
                            ${color.replace('0.8', '0.4')} 240deg,
                            transparent 360deg
                        )`,
                        zIndex: -1
                    }}
                />

                {/* Main Card Content */}
                <div style={{
                    position: 'relative',
                    width: '100%',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    alignItems: 'center',
                    padding: '2rem',
                    textAlign: 'center',
                    borderRadius: '24px',
                    background: isLight
                        ? `linear-gradient(145deg,
                            rgba(15, 23, 42, 0.06),
                            rgba(15, 23, 42, 0.03)
                        )`
                        : `linear-gradient(145deg,
                            rgba(255, 255, 255, 0.1),
                            rgba(255, 255, 255, 0.05)
                        )`,
                    backdropFilter: 'blur(25px) saturate(180%)',
                    border: isLight
                        ? '1px solid rgba(15, 23, 42, 0.12)'
                        : '1px solid rgba(255, 255, 255, 0.2)',
                    boxShadow: isLight
                        ? `0 8px 32px rgba(15, 23, 42, 0.12),
                           0 2px 8px rgba(15, 23, 42, 0.08),
                           inset 0 1px 0 rgba(255, 255, 255, 0.5),
                           inset 0 -1px 0 rgba(15, 23, 42, 0.05)`
                        : `0 8px 32px rgba(0, 0, 0, 0.3),
                           0 2px 8px rgba(0, 0, 0, 0.2),
                           inset 0 1px 0 rgba(255, 255, 255, 0.3),
                           inset 0 -1px 0 rgba(255, 255, 255, 0.1)`,
                    overflow: 'hidden'
                }}>
                    
                    {/* Background image requested by user */}
                    <div 
                        style={{
                            position: 'absolute',
                            inset: 0,
                            backgroundImage: `url(https://images.unsplash.com/photo-1550439062-609e1531270e?q=80&w=2000&auto=format&fit=crop)`,
                            backgroundSize: 'cover',
                            backgroundPosition: 'center',
                            opacity: isLight ? 0.07 : 0.15,
                            zIndex: -1
                        }}
                    />

                    {/* Enhanced Glass reflection overlay */}
                    <div style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        height: '60%',
                        background: isLight
                            ? 'linear-gradient(135deg, rgba(255, 255, 255, 0.35) 0%, rgba(255, 255, 255, 0.12) 50%, transparent 100%)'
                            : 'linear-gradient(135deg, rgba(255, 255, 255, 0.25) 0%, rgba(255, 255, 255, 0.1) 50%, transparent 100%)',
                        pointerEvents: 'none',
                        borderRadius: '24px 24px 0 0'
                    }} />

                    {/* Glass shine effect */}
                    <div style={{
                        position: 'absolute',
                        top: '10px',
                        left: '10px',
                        right: '10px',
                        height: '2px',
                        background: 'linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.6) 50%, transparent 100%)',
                        borderRadius: '1px',
                        pointerEvents: 'none',
                        opacity: isLight ? 0.5 : 1
                    }} />

                    {/* Side glass reflection */}
                    <div style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '2px',
                        height: '100%',
                        background: 'linear-gradient(180deg, rgba(255, 255, 255, 0.3) 0%, transparent 50%)',
                        borderRadius: '24px 0 0 24px',
                        pointerEvents: 'none'
                    }} />

                    {/* Frosted glass texture */}
                    <div style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        bottom: 0,
                        backgroundImage: `
                            radial-gradient(circle at 20% 30%, rgba(255,255,255,0.1) 1px, transparent 2px),
                            radial-gradient(circle at 80% 70%, rgba(255,255,255,0.08) 1px, transparent 2px),
                            radial-gradient(circle at 40% 80%, rgba(255,255,255,0.06) 1px, transparent 2px)
                        `,
                        backgroundSize: '30px 30px, 25px 25px, 35px 35px',
                        pointerEvents: 'none',
                        borderRadius: '24px',
                        opacity: isLight ? 0.35 : 0.7
                    }} />
                    
                    {/* Rendered Text Content */}
                    <div className="z-10 flex flex-col items-center gap-6">
                        <div 
                            style={{ 
                                background: color, 
                                boxShadow: `0 0 20px ${color}`
                            }} 
                            className="p-4 rounded-2xl bg-opacity-20"
                        >
                            {getIcon(id)}
                        </div>
                        <h2 className={`text-3xl font-bold tracking-tight drop-shadow-md ${isLight ? 'text-foreground' : 'text-white'}`}>
                            {title}
                        </h2>
                        <p className={`text-lg max-w-lg drop-shadow-sm ${isLight ? 'text-muted-foreground' : 'text-white/80'}`}>
                            {description}
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};

export const StackedCards: React.FC = () => {
    const containerRef = useRef<HTMLDivElement>(null);
    // Existing Revora theme mechanism (same as dashboard layout / home /
    // setup-guide): live-switches with the global theme toggle.
    const { theme } = useThemeStore();
    const isLight = theme === 'light';

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        gsap.fromTo(container,
            { opacity: 0 },
            {
                opacity: 1,
                duration: 1.2,
                ease: "power2.out"
            }
        );
    }, []);

    return (
        // Transparent: the (dashboard) layout behind this page already
        // renders the standard Revora background (theme-aware shell plus
        // the shared DotGrid), exactly like the review/repositories pages.
        <main ref={containerRef} style={{ background: 'transparent', minHeight: '100vh' }}>
            {/* Hero Section */}
            <section className={isLight ? 'text-foreground' : 'text-white'} style={{
                height: '70vh',
                width: '100%',
                display: 'grid',
                placeContent: 'center',
                position: 'relative'
            }}>
                <div style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundImage: isLight
                        ? `linear-gradient(to right, rgba(100, 116, 139, 0.20) 1px, transparent 1px),
                           linear-gradient(to bottom, rgba(100, 116, 139, 0.20) 1px, transparent 1px)`
                        : `linear-gradient(to right, rgba(79, 79, 79, 0.18) 1px, transparent 1px),
                           linear-gradient(to bottom, rgba(79, 79, 79, 0.18) 1px, transparent 1px)`,
                    backgroundSize: '54px 54px',
                    maskImage: 'radial-gradient(ellipse 60% 50% at 50% 0%, #000 70%, transparent 100%)'
                }} />
                <h1 style={{
                    fontSize: 'clamp(2rem, 5vw, 4rem)',
                    fontWeight: '500',
                    textAlign: 'center',
                    lineHeight: '1.2',
                    padding: '0 2rem',
                    position: 'relative',
                    zIndex: 1
                }}>
                    Getting Started with Revora <br /> Scroll down! 👇
                </h1>
            </section>

            {/* Cards Section */}
            <section className={isLight ? 'text-foreground' : 'text-white'} style={{
                width: '100%',
                paddingBottom: '20vh'
            }}>
                {cardData.map((card, index) => {
                    return (
                        <Card
                            key={card.id}
                            id={card.id}
                            title={card.title}
                            description={card.description}
                            index={index}
                            totalCards={cardData.length}
                            color={card.color}
                            isLight={isLight}
                        />
                    );
                })}
            </section>
        </main>
    );
};
